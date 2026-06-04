#!/usr/bin/env python3
"""
test_app.py — integration test for the product API (auth → keys → run → report →
live leaderboard) against SQLite with provider calls stubbed. Runs standalone:

    python tests/test_app.py

Verifies the legitimacy gates (unverified users blocked, quota enforced), the full
run lifecycle, and that every data point lands in Postgres-shaped tables.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages"))

# Configure env BEFORE importing the app.
_DB = Path(tempfile.gettempdir()) / "xodexa_apptest.db"
if _DB.exists():
    _DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["KEY_ENCRYPTION_KEY"] = ""  # dev-derived key (stable within process)
os.environ["SESSION_SECRET"] = "test-secret"
os.environ["RUN_INLINE"] = "1"

from fastapi.testclient import TestClient  # noqa: E402
from apps.server import main, providers, routes_runs  # noqa: E402
from apps.server.db import session, init_db  # noqa: E402

init_db()  # TestClient without a context manager doesn't fire startup events
from apps.server import models as M  # noqa: E402
from apps.worker import run_job  # noqa: E402
from xodexa import CallableConnector  # noqa: E402

# --- stub the provider so no real API key / network is needed ---
providers.validate_key = lambda p, k, b=None: {"ok": True, "detail": "stub",
                                               "models": ["stub-model"]}
providers.validate_model = lambda p, k, m, b=None: True
providers.connector = lambda p, k, m, b=None: CallableConnector(
    lambda prompt: "The answer is 42.", name="stub")
# run synchronously so the test is deterministic
routes_runs.enqueue_run = lambda run_id, inline_key=None, inline_base_url=None: \
    run_job.execute_run(run_id, inline_key, inline_base_url)

client = TestClient(main.app)
PASSED = []


def check(name, cond):
    PASSED.append((name, bool(cond)))
    print(("  ✓ " if cond else "  ✗ ") + name)


def _ssrf_blocked(url):
    # assert_safe_base_url is NOT stubbed (only validate_key/validate_model/connector are)
    try:
        providers.assert_safe_base_url(url)
        return False
    except providers.ProviderError:
        return True


def run():
    # 1. register
    r = client.post("/api/auth/register",
                    json={"username": "tester", "email": "t@example.com",
                          "password": "supersecret"})
    check("register 200", r.status_code == 200)

    # weak password rejected
    r2 = client.post("/api/auth/register",
                     json={"username": "x2", "email": "x2@e.com", "password": "short"})
    check("weak password rejected (422)", r2.status_code == 422)

    # 2. cannot login before verify
    r = client.post("/api/auth/login", json={"identifier": "t@example.com",
                                             "password": "supersecret"})
    check("login blocked until verified (403)", r.status_code == 403)

    # grab the verification token from the DB and verify
    db = session()
    ev = db.query(M.EmailVerification).first()
    check("verification token created", ev is not None)
    r = client.get(f"/api/auth/verify?token={ev.token}", follow_redirects=False)
    check("verify redirects (303)", r.status_code == 303 and "success" in r.headers["location"])

    # 3. login
    r = client.post("/api/auth/login", json={"identifier": "tester",
                                             "password": "supersecret"})
    check("login after verify (200)", r.status_code == 200)
    csrf = r.json().get("csrf_token")
    check("csrf token issued", bool(csrf))
    H = {"x-csrf-token": csrf}

    # CSRF required for mutating call
    r = client.post("/api/credentials", json={"provider": "openai", "key": "sk-test123"})
    check("missing CSRF rejected (403)", r.status_code == 403)

    # 4. add credential (provider stubbed) -> validated + encrypted
    r = client.post("/api/credentials", headers=H,
                    json={"provider": "openai", "label": "main", "key": "sk-secret-key-1234"})
    check("credential added (200)", r.status_code == 200)
    cred_id = r.json()["credential"]["id"]
    db = session()
    cred = db.query(M.ProviderCredential).first()
    check("key stored encrypted (not plaintext)",
          cred.key_encrypted is not None and b"sk-secret" not in (cred.key_encrypted or b""))
    check("only last4 exposed", r.json()["credential"]["key_last4"] == "1234")

    # 5. quota: too many tasks rejected
    r = client.post("/api/runs", headers=H,
                    json={"credential_id": cred_id, "model_name": "stub-model", "n_tasks": 99999})
    check("oversized run rejected (422)", r.status_code == 422)

    # 6. launch a real (stubbed) run -> runs synchronously -> scored
    r = client.post("/api/runs", headers=H,
                    json={"credential_id": cred_id, "model_name": "stub-model",
                          "n_tasks": 12, "family": "math", "visibility": "public"})
    check("run created (200)", r.status_code == 200)
    run_id = r.json()["run"]["id"]
    r = client.get(f"/api/runs/{run_id}")
    status = r.json()["run"]["status"]
    check("run scored", status == "scored")
    check("run has a Xodexa score", r.json()["run"]["xodexa_score"] is not None)
    # regression: seed must fit Postgres INT4 (signed) or inserts 500 on Postgres
    check("run seed fits INT4", session().get(M.WebRun, run_id).seed <= 0x7FFFFFFF)

    # 7. report exists + is viewable + has the engine sections
    r = client.get(f"/api/runs/{run_id}/report")
    rep = r.json()
    check("report has agi_readiness + improvement_path",
          "agi_readiness" in rep and "improvement_path" in rep)
    r = client.get(f"/api/runs/{run_id}/report.md")
    check("markdown export works", r.status_code == 200 and "Xodexa Score" in r.text)

    # 8. live leaderboard now shows the real run
    r = client.get("/api/leaderboard")
    lb = r.json()
    check("live leaderboard shows the run", lb["count"] == 1 and
          lb["entries"][0]["run_id"] == run_id)

    # 9. dashboard KPIs reflect it
    r = client.get("/api/dashboard")
    check("dashboard verified_runs == 1", r.json()["kpis"]["verified_runs"] == 1)

    # 10. every data point persisted
    db = session()
    check("responses persisted", db.query(M.WebRunResponse).filter_by(run_id=run_id).count() == 12)
    check("item scores persisted", db.query(M.WebRunItemScore).filter_by(run_id=run_id).count() == 12)
    check("hash-chained events persisted", db.query(M.RunEvent).filter_by(run_id=run_id).count() >= 13)
    check("report row persisted", db.query(M.Report).filter_by(run_id=run_id).count() == 1)
    check("audit log populated", db.query(M.AuditLog).count() >= 3)

    # 10b. security guards (SSRF + model-name charset) — see security review
    check("SSRF guard blocks metadata IP", _ssrf_blocked("http://169.254.169.254/"))
    check("SSRF guard blocks loopback", _ssrf_blocked("http://127.0.0.1:6379"))
    check("SSRF guard blocks private 10.x", _ssrf_blocked("http://10.0.0.5/v1"))
    check("SSRF guard blocks file scheme", _ssrf_blocked("file:///etc/passwd"))
    check("SSRF guard allows public https", not _ssrf_blocked("https://api.openai.com/v1"))
    check("model name rejects markup", not providers.is_safe_model_name("<img src=x onerror=1>"))
    check("model name allows gpt-4o", providers.is_safe_model_name("gpt-4o"))
    r = client.post("/api/runs", headers=H, json={"credential_id": cred_id,
                    "model_name": "<svg onload=alert(1)>", "n_tasks": 10})
    check("run rejects XSS model_name (422)", r.status_code == 422)

    # 11. logout
    r = client.post("/api/auth/logout", headers=H)
    check("logout (200)", r.status_code == 200)
    r = client.get("/api/auth/me")
    check("me reports logged out", r.json()["authenticated"] is False)

    ok = sum(1 for _, c in PASSED if c)
    print(f"\n{ok}/{len(PASSED)} app integration checks passed")
    return 0 if ok == len(PASSED) else 1


if __name__ == "__main__":
    print("Xodexa app integration test\n" + "-" * 40)
    sys.exit(run())
