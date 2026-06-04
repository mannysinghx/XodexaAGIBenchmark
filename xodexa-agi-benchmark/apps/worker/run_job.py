"""
apps.worker.run_job
=====================
Executes a web-initiated benchmark run against a REAL model, end to end:

  resolve key (saved credential → decrypt, or use-once key passed in) → generate a
  fresh seeded pack → call the provider per task (raw outputs) → persist every response
  + a hash-chained event → central re-score (xodexa.evaluate) → signed report
  (xodexa.report) → persist scores/report/leaderboard fields → mark scored.

Runs as an RQ job (Redis) in production, or inline (dev) — same function either way.
No secrets are logged. Per-task provider errors are recorded; an auth-class failure
aborts the run cleanly as 'failed'.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

from apps.server import providers, security
from apps.server.db import session
from apps.server.models import (ProviderCredential, Report, RunEvent, WebRun,
                                WebRunItemScore, WebRunResponse)

from xodexa import generators as G, schema, evaluate, report as report_mod
from xodexa.crypto import KeyPair, sha256_hex, canonical

logger = logging.getLogger("xodexa.run")


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _append_event(db, run_id: str, seq: int, prev_hash: str, kind: str, data: dict) -> str:
    h = sha256_hex((prev_hash + sha256_hex(canonical(data))).encode())
    db.add(RunEvent(run_id=run_id, seq=seq, kind=kind, data=data, hash=h, prev_hash=prev_hash))
    return h


def execute_run(run_id: str, inline_key: str | None = None,
                inline_base_url: str | None = None) -> dict:
    db = session()
    try:
        run = db.get(WebRun, run_id)
        if not run:
            return {"ok": False, "error": "run not found"}
        run.status = "running"
        run.started_at = _now()
        run.progress = 0
        db.commit()

        # resolve key + base_url
        base_url = inline_base_url
        key = inline_key
        if run.credential_id:
            cred = db.get(ProviderCredential, run.credential_id)
            if not cred:
                return _fail(db, run, "credential no longer exists")
            key = security.decrypt_secret(cred.key_encrypted) if cred.key_encrypted else ""
            base_url = cred.base_url
        if key is None:
            return _fail(db, run, "no API key available for this run")

        try:
            conn = providers.connector(run.provider, key, run.model_name, base_url)
        except providers.ProviderError as e:
            return _fail(db, run, f"connector error: {e}")

        # generate a fresh, seeded pack (answers stay server-side)
        tasks = G.generate(family=run.family, n=run.n_tasks, seed=run.seed,
                           visibility="validation")
        keys = {t.task_id: schema.answer_key(t) for t in tasks}

        seq = 0
        prev = "0" * 64
        prev = _append_event(db, run.id, seq, prev, "run_start",
                             {"model": run.model_name, "provider": run.provider,
                              "n_tasks": len(tasks)})
        seq += 1
        db.commit()
        logger.info("run %s start: model=%s provider=%s base_url=%s n_tasks=%d",
                    run.id, run.model_name, run.provider, base_url or "(default)", len(tasks))

        responses = []
        consecutive_errors = 0
        last_error = None
        total_tokens = 0
        total_latency = 0.0
        for i, t in enumerate(tasks):
            out, latency_ms, err = "", 0.0, None
            t0 = time.perf_counter()
            try:
                out = conn.complete(t.prompt)
                consecutive_errors = 0
            except Exception as e:  # noqa: BLE001 — provider/network error (detail kept)
                err = f"{type(e).__name__}: {e}"
                last_error = err
                consecutive_errors += 1
                logger.warning("run %s task %s (model=%s) failed [%d in a row]: %s",
                               run.id, t.task_id, run.model_name, consecutive_errors, err)
            latency_ms = (time.perf_counter() - t0) * 1000
            toks = max(1, len(out) // 4)
            total_tokens += toks
            total_latency += latency_ms
            responses.append({"id": t.task_id, "output": out, "latency_ms": latency_ms,
                              "tokens": toks})
            db.add(WebRunResponse(run_id=run.id, task_id=t.task_id, family=t.task_family,
                                  output=out, output_sha256=sha256_hex((out or "").encode()),
                                  latency_ms=round(latency_ms, 2), tokens=toks))
            ev = {"id": t.task_id, "ok": err is None,
                  "output_sha256": sha256_hex((out or "").encode())}
            if err:
                ev["error"] = err[:500]
            prev = _append_event(db, run.id, seq, prev, "task_response", ev)
            seq += 1
            run.progress = int(100 * (i + 1) / len(tasks))
            if i % 5 == 0 or i == len(tasks) - 1:
                db.commit()
            # abort early if the provider is rejecting us (bad key / model / quota)
            if consecutive_errors >= 5:
                msg = f"provider call failed {consecutive_errors}× in a row — last error: {last_error}"
                logger.error("run %s aborted: %s", run.id, msg)
                return _fail(db, run, msg)

        # --- central re-scoring + signed report ---
        er = evaluate.score_pack(keys, responses)
        signer = KeyPair.generate()
        rep = report_mod.build_report(
            run.model_name, f"Xodexa Live ({run.provider})", er,
            telemetry={"tokens": total_tokens, "latency_ms": round(total_latency),
                       "avg_latency_ms": round(total_latency / max(1, len(responses)), 1)},
            signer=signer)
        rep["family_scores"] = er["family_scores"]  # for the live leaderboard/compare pages

        for it in er["per_item"]:
            db.add(WebRunItemScore(run_id=run.id, task_id=it["task_id"], family=it["family"],
                                   category=it["category"], awarded=it["awarded"],
                                   max_points=it["max"], verdict=it["verdict"],
                                   difficulty=it.get("difficulty")))
        ar = rep["agi_readiness"]
        db.add(Report(run_id=run.id, user_id=run.user_id, report_json=rep,
                      xodexa_score=rep["xodexa_score"], grade=rep["grade"],
                      agi_index=ar["agi_readiness_index"], agi_level=ar["level"],
                      body_sha256=rep["verification_appendix"]["body_sha256"],
                      signer_pub=rep["verification_appendix"]["signer_pub"],
                      signature=rep["verification_appendix"]["signature"]))

        run.xodexa_score = rep["xodexa_score"]
        run.grade = rep["grade"]
        run.agi_index = ar["agi_readiness_index"]
        run.agi_level = ar["level"]
        run.accuracy = rep["frontier_metrics"]["accuracy"]
        run.calibration_error = rep["frontier_metrics"]["calibration_error"]
        run.tokens = total_tokens
        run.latency_ms = round(total_latency, 1)
        run.progress = 100
        run.status = "scored"
        run.finished_at = _now()
        _append_event(db, run.id, seq, prev, "run_scored",
                      {"xodexa_score": run.xodexa_score, "agi_level": run.agi_level})
        db.commit()
        logger.info("run %s scored: xodexa_score=%s grade=%s agi_level=%s",
                    run.id, run.xodexa_score, run.grade, run.agi_level)
        return {"ok": True, "run_id": run.id, "xodexa_score": run.xodexa_score}
    except Exception as e:  # noqa: BLE001 — never leave a run stuck; record the reason
        logger.exception("run %s crashed", run_id)
        try:
            db.rollback()
            run = db.get(WebRun, run_id)
            if run and run.status not in ("scored", "failed"):
                run.status = "failed"
                run.error = f"internal error: {type(e).__name__}: {e}"
                run.finished_at = _now()
                db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("run %s: failed to record failure", run_id)
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        db.close()


def _fail(db, run: WebRun, message: str) -> dict:
    run.status = "failed"
    run.error = message
    run.finished_at = _now()
    db.commit()
    return {"ok": False, "error": message}
