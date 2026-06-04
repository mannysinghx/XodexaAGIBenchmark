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

import json  # noqa: E402
import logging  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from xodexa import (ScoringAuthority, suites, families, generators, anchors,  # noqa: E402
                    registry)

AUTH = ScoringAuthority()
PLUGIN_REGISTRY = registry.PluginRegistry()
_REPO = Path(__file__).resolve().parents[2]


def _read_json(rel: str):
    p = _REPO / rel
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))

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

    # ---- platform layer (read surfaces over the catalog + generated artifacts) ----

    @app.get("/v1/families")
    def families_catalog():
        """The 12 task families + the 12 scoring dimensions + grade/AGI bands."""
        return {
            "families": {k: {"title": f.title, "blurb": f.blurb,
                             "subdomains": list(f.subdomains)}
                         for k, f in families.FAMILIES.items()},
            "score_weights": families.SCORE_WEIGHTS,
            "grade_bands": [{"lo": lo, "hi": hi, "name": n}
                            for lo, hi, n in families.GRADE_BANDS],
            "agi_levels": [{"level": L.level, "name": L.name, "blurb": L.blurb}
                           for L in families.AGI_LEVELS],
        }

    @app.get("/v1/generators")
    def generator_catalog(family: str | None = None):
        """Layer-3 dynamic generator catalog."""
        specs = generators.list_generators(family)
        return {"count": len(specs),
                "generators": [{"generator_id": s.generator_id, "family": s.family,
                                "blurb": (s.blurb or "").strip().split("\n")[0][:160]}
                               for s in specs]}

    @app.get("/v1/anchors")
    def anchor_catalog(dimension: str | None = None):
        """Layer-0 public calibration benchmark anchors (with contamination risk)."""
        a = anchors.list_anchors(dimension)
        return {"summary": anchors.contamination_summary(),
                "anchors": [vars(x) for x in a]}

    @app.get("/v1/datasets")
    def datasets():
        """The seed corpus summary (run scripts/build_seed.py to populate)."""
        s = _read_json("datasets/SUMMARY.json")
        if s is None:
            raise HTTPException(404, "no datasets built yet — run scripts/build_seed.py")
        return s

    @app.get("/v1/platform/leaderboard")
    def platform_leaderboard():
        """The AGI-readiness leaderboard from demo/platform_demo.py."""
        s = _read_json("results/platform_leaderboard.json")
        if s is None:
            raise HTTPException(404, "no platform leaderboard yet — run demo/platform_demo.py")
        return s

    @app.post("/v1/plugins/validate")
    def plugin_validate(manifest: dict):
        """Validate a plugin manifest against the registry security policy."""
        return {"violations": registry.validate_manifest(manifest)}

    @app.post("/v1/plugins/install")
    def plugin_install(manifest: dict):
        return PLUGIN_REGISTRY.install(manifest)

    # ===================== Product layer (auth, keys, runs, live data) =========
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from apps.server.config import get_settings as _get_settings
    from apps.server.db import init_db as _init_db
    from apps.server import (routes_auth, routes_keys, routes_runs, routes_public)

    _settings = _get_settings()

    if _settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=_settings.cors_origins,
                           allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.on_event("startup")
    def _startup():
        _init_db()

    app.include_router(routes_auth.router)
    app.include_router(routes_keys.router)
    app.include_router(routes_runs.router)
    app.include_router(routes_public.router)

    # Serve the static frontend LAST so /api and /v1 routes take precedence.
    _STATIC = _REPO / "frontend" / "public"
    if _STATIC.is_dir():
        app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="static")
else:  # pragma: no cover
    app = None
