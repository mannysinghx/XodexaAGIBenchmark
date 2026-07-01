"""Phase-4 infra hardening tests: dynamic timeout, cost estimation, stale-run
reaper, metrics, JSON logging, Redis-or-memory rate limiter, and the worker's
idempotent resume path (via a monkeypatched connector, no real provider)."""

import datetime as dt
import json
import logging

import pytest

from apps.server.runtime import (
    JsonLogFormatter,
    collect_metrics,
    estimate_cost,
    prometheus_text,
    reap_stale_runs,
    run_timeout_seconds,
)


# --------------------------------------------------------------------------- #
# Dynamic timeout + cost
# --------------------------------------------------------------------------- #

def test_timeout_scales_with_tasks_and_clamps():
    assert run_timeout_seconds(5) == 600           # floor
    assert run_timeout_seconds(200) > run_timeout_seconds(40)
    assert run_timeout_seconds(100000) == 21600    # ceiling


def test_cost_estimate_scales_and_zero_for_selfhosted():
    c = estimate_cost(100, "anthropic")
    assert c["est_total_tokens"] == 100 * (400 + 350)
    assert c["est_usd"] > 0
    assert estimate_cost(100, "ollama")["est_usd"] == 0.0


# --------------------------------------------------------------------------- #
# Reaper + metrics (SQLite)
# --------------------------------------------------------------------------- #

@pytest.fixture
def db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from apps.server.db import Base
    import apps.server.models  # noqa: F401 — register mappers
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def _mk_run(db, status, started_minutes_ago=None):
    from apps.server.models import WebRun
    now = dt.datetime.now(dt.timezone.utc)
    started = (now - dt.timedelta(minutes=started_minutes_ago)
               if started_minutes_ago is not None else None)
    r = WebRun(user_id="u1", provider="openai", model_name="m", family="reasoning",
               n_tasks=10, seed=1, visibility="public", status=status,
               started_at=started, created_at=started or now)
    db.add(r)
    db.commit()
    return r


def test_reaper_fails_only_overdue_running(db):
    fresh = _mk_run(db, "running", started_minutes_ago=5)
    stale = _mk_run(db, "running", started_minutes_ago=600)
    scored = _mk_run(db, "scored", started_minutes_ago=600)
    reaped = reap_stale_runs(db, max_running_seconds=3600)
    assert stale.id in reaped and fresh.id not in reaped
    db.refresh(fresh); db.refresh(stale); db.refresh(scored)
    assert fresh.status == "running"
    assert stale.status == "failed" and "stale" in stale.error
    assert scored.status == "scored"  # untouched


def test_reaper_idempotent(db):
    _mk_run(db, "running", started_minutes_ago=600)
    first = reap_stale_runs(db, max_running_seconds=3600)
    second = reap_stale_runs(db, max_running_seconds=3600)
    assert len(first) == 1 and second == []


def test_metrics_snapshot_and_prometheus(db):
    _mk_run(db, "scored")
    _mk_run(db, "scored")
    _mk_run(db, "failed")
    _mk_run(db, "running")
    m = collect_metrics(db)
    assert m["runs_total"] == 4
    assert m["runs_scored"] == 2 and m["runs_failed"] == 1
    assert m["error_rate"] == pytest.approx(1 / 3, abs=1e-3)
    text = prometheus_text(m)
    assert 'xodexa_runs_state{state="scored"} 2' in text
    assert "xodexa_error_rate" in text


# --------------------------------------------------------------------------- #
# JSON logging
# --------------------------------------------------------------------------- #

def test_json_log_formatter_includes_extra_fields():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    rec.run_id = "run_123"
    out = json.loads(JsonLogFormatter().format(rec))
    assert out["msg"] == "hello world" and out["run_id"] == "run_123"
    assert out["level"] == "INFO" and "ts" in out


# --------------------------------------------------------------------------- #
# Rate limiter (in-memory path)
# --------------------------------------------------------------------------- #

def test_ratelimit_blocks_after_limit():
    from apps.server import ratelimit
    ratelimit.reset()
    key = "login:1.2.3.4"
    assert all(ratelimit.allow(key, limit=3, window=60) for _ in range(3))
    assert not ratelimit.allow(key, limit=3, window=60)  # 4th blocked


def test_ratelimit_separate_keys_independent():
    from apps.server import ratelimit
    ratelimit.reset()
    assert ratelimit.allow("a", 1, 60)
    assert not ratelimit.allow("a", 1, 60)
    assert ratelimit.allow("b", 1, 60)  # different key unaffected


# --------------------------------------------------------------------------- #
# Idempotent resume (worker)
# --------------------------------------------------------------------------- #

def test_execute_run_resumes_without_recalling_provider(monkeypatch):
    """A second execute_run for the same run reuses answered tasks and does not call
    the provider for them."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from apps.server.db import Base
    import apps.server.models as models
    from apps.server.models import WebRun, WebRunResponse
    from apps.worker import run_job
    from xodexa.runner import CallableConnector

    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    monkeypatch.setattr(run_job, "session", Session)

    # Count provider calls; always return a plausible answer.
    calls = {"n": 0}

    def fake_complete(prompt, assets=None):
        calls["n"] += 1
        return "The answer is 42. Confidence: 55"

    def fake_connector(provider, key, model, base_url):
        return CallableConnector(fake_complete, name="fake")

    monkeypatch.setattr(run_job.providers, "connector", fake_connector)

    s = Session()
    run = WebRun(user_id="u1", provider="openai", model_name="m", family="reasoning",
                 n_tasks=6, seed=42, visibility="public", status="queued")
    s.add(run)
    s.commit()
    run_id = run.id
    s.close()

    run_job.execute_run(run_id, inline_key="k")
    first_calls = calls["n"]
    assert first_calls == 6  # one per task

    # Simulate a retry: run it again. All 6 are already answered -> zero new calls.
    run_job.execute_run(run_id, inline_key="k")
    assert calls["n"] == first_calls  # provider NOT called again

    s = Session()
    rows = s.query(WebRunResponse).filter_by(run_id=run_id).count()
    assert rows == 6  # no duplicate trace rows
    final = s.get(WebRun, run_id)
    assert final.status == "scored"
    s.close()
