"""
Xodexa AGI Benchmark — main app (central Scoring Authority) HTTP surface.

FastAPI wrapper that exposes the trust kernel in xodexa over REST + OpenAPI. The
endpoints map 1:1 to the runner API flow in the spec (register -> challenge -> manifest
-> submit -> verify+score -> publish). A single in-memory ScoringAuthority backs the
MVP; production swaps it for the Postgres-backed store in db/schema.sql behind the same
methods.

Run:  uvicorn apps.server.main:app --reload   (pip install fastapi uvicorn pydantic)
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except Exception:  # allow import without fastapi installed (scaffold inspection)
    FastAPI = None

from xodexa import ScoringAuthority, suites  # noqa: E402

AUTH = ScoringAuthority()

if FastAPI:
    app = FastAPI(title="Xodexa AGI Benchmark — Scoring Authority", version="1.0.0",
                  description="The world's most unforgiving open benchmark "
                              "infrastructure for frontier AI. Central, trusted "
                              "scoring authority. The runner never receives answer "
                              "keys and can never write a leaderboard score.")

    class RegisterReq(BaseModel):
        runner_pub: str
        runner_version: str = "0.1.0"

    class ConfirmReq(BaseModel):
        runner_id: str
        signed_challenge: str

    class ManifestReq(BaseModel):
        runner_id: str
        pack_id: str = "xodexa-omega"
        mode: str = "official"

    class Bundle(BaseModel):
        bundle: dict

    @app.get("/health")
    def health():
        return {"status": "ok", "benchmark_version": "1.0.0",
                "server_pub_fp": __import__("xodexa").fingerprint(AUTH.server_pub())}

    @app.get("/v1/benchmarks")
    def benchmarks():
        return suites.list_packs()

    @app.post("/v1/runners/register")
    def register(req: RegisterReq):
        """Step 1-2: register a runner, receive a key-possession challenge."""
        return AUTH.register_runner(req.runner_pub, req.runner_version)

    @app.post("/v1/runners/confirm")
    def confirm(req: ConfirmReq):
        """Step 3: prove possession of the runner private key."""
        ok = AUTH.confirm_runner(req.runner_id, req.signed_challenge)
        if not ok:
            raise HTTPException(401, "challenge verification failed")
        return {"verified": True}

    @app.post("/v1/runs/manifest")
    def manifest(req: ManifestReq):
        """Step 5-6: issue a server-signed manifest + prompts-only task bundle."""
        try:
            return AUTH.issue_manifest(req.runner_id, req.pack_id, req.mode)
        except PermissionError as e:
            raise HTTPException(403, str(e))
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/v1/runs/submit")
    def submit(body: Bundle):
        """Step 10-14: verify + central re-score + publish official record."""
        return AUTH.verify_and_score(body.bundle)

    @app.get("/v1/leaderboard")
    def leaderboard(verified_only: bool = True, attested_only: bool = False):
        rows = list(AUTH.leaderboard)
        if attested_only:
            rows = [r for r in rows if r["attestation"] != "none"]
        rows.sort(key=lambda r: r["apex_score"], reverse=True)
        return {"entries": rows, "count": len(rows)}
else:  # pragma: no cover
    app = None
