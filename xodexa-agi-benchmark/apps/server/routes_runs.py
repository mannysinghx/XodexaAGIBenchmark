"""
apps.server.routes_runs
=========================
Launch + monitor real benchmark runs. Gated: verified user, validated key + model,
per-user quota. Runs against the user's own provider key (saved credential or a
use-once key that's never persisted). Reports are free to view + export.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.server import providers, security
from apps.server.db import get_db
from apps.server.deps import (audit, csrf_protect, enforce_run_quota, record_run_started,
                              require_verified)
from apps.server.models import ProviderCredential, Report, WebRun
from apps.server.queue import enqueue_run

from xodexa import families

router = APIRouter(prefix="/api", tags=["runs"])


class RunReq(BaseModel):
    model_name: str
    family: str | None = None
    n_tasks: int = 40
    visibility: str = "public"
    credential_id: str | None = None
    # use-once / inline path (only when no credential_id):
    provider: str | None = None
    key: str | None = None
    base_url: str | None = None
    save_key: bool = False
    label: str = ""


def _run_public(r: WebRun) -> dict:
    return {"id": r.id, "model_name": r.model_name, "provider": r.provider,
            "family": r.family, "n_tasks": r.n_tasks, "visibility": r.visibility,
            "status": r.status, "progress": r.progress, "error": r.error,
            "xodexa_score": r.xodexa_score, "grade": r.grade, "agi_index": r.agi_index,
            "agi_level": r.agi_level, "accuracy": r.accuracy,
            "calibration_error": r.calibration_error, "tokens": r.tokens,
            "latency_ms": r.latency_ms,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None}


@router.post("/runs", dependencies=[Depends(csrf_protect)])
def create_run(body: RunReq, request: Request,
               user=Depends(require_verified), db: Session = Depends(get_db)):
    if body.family and body.family not in families.FAMILY_KEYS:
        raise HTTPException(422, f"unknown family; choose from {list(families.FAMILY_KEYS)}")
    if body.visibility not in ("public", "private"):
        raise HTTPException(422, "visibility must be public or private")
    enforce_run_quota(db, user.id, body.n_tasks)

    inline_key = None
    base_url = None
    credential_id = None

    if body.credential_id:
        cred = db.query(ProviderCredential).filter_by(
            id=body.credential_id, user_id=user.id).first()
        if not cred or cred.status != "validated":
            raise HTTPException(400, "credential not found or not validated")
        provider = cred.provider
        base_url = cred.base_url
        credential_id = cred.id
        key_for_validation = security.decrypt_secret(cred.key_encrypted) if cred.key_encrypted else ""
    else:
        provider = body.provider
        if provider not in providers.PROVIDERS:
            raise HTTPException(422, "provide credential_id, or a provider + key")
        if not body.key and provider != "openai-compatible":
            raise HTTPException(422, "an API key is required")
        try:
            res = providers.validate_key(provider, body.key or "", body.base_url)
        except providers.ProviderError as e:
            raise HTTPException(502, str(e))
        if not res.get("ok"):
            raise HTTPException(400, f"key rejected: {res.get('detail')}")
        base_url = body.base_url
        key_for_validation = body.key or ""
        if body.save_key:
            cred = ProviderCredential(
                user_id=user.id, provider=provider, label=body.label[:64],
                key_encrypted=security.encrypt_secret(body.key) if body.key else None,
                key_last4=body.key[-4:] if body.key else "", base_url=base_url,
                status="validated", validated_at=security.now())
            db.add(cred)
            db.commit()
            credential_id = cred.id
        else:
            inline_key = body.key or ""  # use-once: passed to worker, never stored

    # validate the model name against the provider (legitimacy gate)
    try:
        if not providers.validate_model(provider, key_for_validation, body.model_name, base_url):
            raise HTTPException(400, f"model '{body.model_name}' is not available for this key")
    except providers.ProviderError as e:
        raise HTTPException(502, str(e))

    seed = int.from_bytes(os.urandom(4), "big")
    run = WebRun(user_id=user.id, credential_id=credential_id, provider=provider,
                 model_name=body.model_name.strip(), family=body.family,
                 n_tasks=body.n_tasks, seed=seed, visibility=body.visibility,
                 status="queued")
    db.add(run)
    db.commit()
    record_run_started(db, user.id, body.n_tasks)
    audit(db, request, "run_created", user_id=user.id, run_id=run.id,
          provider=provider, model=run.model_name, n_tasks=run.n_tasks)
    enqueue_run(run.id, inline_key=inline_key, inline_base_url=base_url if inline_key is not None else None)
    return {"ok": True, "run": _run_public(run)}


@router.get("/runs")
def list_runs(user=Depends(require_verified), db: Session = Depends(get_db)):
    rows = (db.query(WebRun).filter_by(user_id=user.id)
            .order_by(WebRun.created_at.desc()).limit(100).all())
    return {"runs": [_run_public(r) for r in rows]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, user=Depends(require_verified), db: Session = Depends(get_db)):
    run = db.query(WebRun).filter_by(id=run_id, user_id=user.id).first()
    if not run:
        raise HTTPException(404, "run not found")
    return {"run": _run_public(run)}


def _load_report(db: Session, run_id: str, request: Request) -> tuple[WebRun, Report]:
    run = db.get(WebRun, run_id)
    if not run:
        raise HTTPException(404, "run not found")
    viewer = security.current_user(request, db)
    is_owner = viewer and viewer.id == run.user_id
    if not is_owner and not (run.visibility == "public" and run.status == "scored"):
        raise HTTPException(403, "not authorized to view this report")
    rep = db.query(Report).filter_by(run_id=run_id).first()
    if not rep:
        raise HTTPException(404, "report not ready")
    return run, rep


@router.get("/runs/{run_id}/report")
def get_report(run_id: str, request: Request, db: Session = Depends(get_db)):
    _, rep = _load_report(db, run_id, request)
    return rep.report_json


@router.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
def get_report_md(run_id: str, request: Request, db: Session = Depends(get_db)):
    run, rep = _load_report(db, run_id, request)
    return _markdown(rep.report_json)


def _markdown(r: dict) -> str:
    ar = r.get("agi_readiness", {})
    ip = r.get("improvement_path", {})
    fa = r.get("failure_analysis", {})
    lines = [
        f"# Xodexa AI Benchmark — Report: {r.get('model_id')}",
        "",
        f"- **Xodexa Score**: {r.get('xodexa_score')}/1000 ({r.get('grade')})  CI {r.get('score_ci95')}",
        f"- **AGI Readiness**: Level {ar.get('level')} — {ar.get('level_name')} "
        f"(index {ar.get('agi_readiness_index')})",
        f"- **Accuracy**: {r.get('frontier_metrics', {}).get('accuracy')}% "
        f"± {r.get('frontier_metrics', {}).get('accuracy_ci95')}  | "
        f"calibration error {r.get('frontier_metrics', {}).get('calibration_error')}",
        f"- **Coverage**: {r.get('coverage')}",
        f"- **Failure rate**: {fa.get('failure_rate')} "
        f"({fa.get('total_failures')}/{fa.get('total_items')})",
        f"- **Time horizon**: {r.get('time_horizon', {}).get('estimated_task_horizon')}",
        "",
        "## Executive summary", "", r.get("executive_summary", ""), "",
        "## AGI Readiness sub-scores", "",
    ]
    for k, v in (ar.get("subscores") or {}).items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Path to AGI — improvement roadmap", "",
              f"_{ip.get('headline','')}_", "",
              "**Recommended next evals:** " + ", ".join(ip.get("recommended_next_evals", [])),
              "**Recommended fine-tuning data:** " + ", ".join(ip.get("recommended_fine_tuning_data", [])),
              "**Recommended RL targets:** " + ", ".join(ip.get("recommended_rl_targets", [])),
              "**Recommended scaffolding:** " + ", ".join(ip.get("recommended_scaffolding_improvements", [])),
              "", "## Verification", "",
              f"- body_sha256: `{r.get('verification_appendix',{}).get('body_sha256')}`",
              f"- signer_pub: `{r.get('verification_appendix',{}).get('signer_pub')}`",
              f"- signature: `{r.get('verification_appendix',{}).get('signature')}`",
              "", "_Unverified local run — scored centrally from your own model's raw outputs._"]
    return "\n".join(lines)
