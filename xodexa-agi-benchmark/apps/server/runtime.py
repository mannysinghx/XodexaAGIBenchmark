"""
apps.server.runtime
======================
Operational helpers that keep long runs reliable and observable without pulling in
heavyweight infra (no Prometheus client, no Celery). Everything here is pure or
DB-only so it is unit-testable against SQLite:

  * dynamic per-run timeout   — a 200-task run on a slow model must not hit a flat
    3600 s wall; the budget scales with task count and an observed per-task ceiling.
  * cost estimation + caps    — a pre-flight token/USD estimate so a run can be
    rejected before it spends the user's provider budget.
  * stale-run reaper          — marks runs stuck in 'running' past a deadline as
    failed, so a worker crash can't leave a run 'running' forever.
  * metrics snapshot          — queue/run/error counts for /metrics.
  * structured logging        — JSON log lines with a run/trace id for correlation.
"""

from __future__ import annotations

import datetime as dt
import json
import logging


# --------------------------------------------------------------------------- #
# Dynamic per-run timeout
# --------------------------------------------------------------------------- #

def run_timeout_seconds(n_tasks: int, per_task_ceiling_s: float = 45.0,
                        overhead_s: float = 120.0, floor_s: float = 600.0,
                        ceiling_s: float = 21600.0) -> int:
    """Wall-clock budget for a run. Scales with task count (each task may retry a
    slow/large model up to the per-task ceiling) plus fixed overhead, clamped to a
    sane floor/ceiling. Replaces the flat 3600 s that 200-task runs blew through."""
    budget = overhead_s + n_tasks * per_task_ceiling_s
    return int(max(floor_s, min(ceiling_s, budget)))


# --------------------------------------------------------------------------- #
# Cost estimation
# --------------------------------------------------------------------------- #

# Coarse per-1k-token USD price table (input, output). Deliberately conservative;
# operators override via PRICE_TABLE env if they want precision. Unknown providers
# fall back to a mid-range default.
DEFAULT_PRICE_PER_1K = {
    "openai": (0.005, 0.015),
    "anthropic": (0.003, 0.015),
    "openai-compatible": (0.0, 0.0),   # self-hosted: no per-token cost
    "ollama": (0.0, 0.0),
    "_default": (0.004, 0.012),
}


def estimate_cost(n_tasks: int, provider: str,
                  avg_prompt_tokens: int = 400, avg_completion_tokens: int = 350,
                  price_table: dict | None = None) -> dict:
    """Pre-flight cost estimate for a run. Returns tokens + USD midpoint estimate.
    Not billing-accurate — a guardrail so a 200-task run's ~$ scale is visible before
    it starts and can be capped."""
    table = price_table or DEFAULT_PRICE_PER_1K
    pin, pout = table.get(provider, table["_default"])
    in_tok = n_tasks * avg_prompt_tokens
    out_tok = n_tasks * avg_completion_tokens
    usd = (in_tok / 1000.0) * pin + (out_tok / 1000.0) * pout
    return {"n_tasks": n_tasks, "provider": provider,
            "est_prompt_tokens": in_tok, "est_completion_tokens": out_tok,
            "est_total_tokens": in_tok + out_tok, "est_usd": round(usd, 4)}


# --------------------------------------------------------------------------- #
# Stale-run reaper
# --------------------------------------------------------------------------- #

def reap_stale_runs(db, max_running_seconds: int = 21600, now: dt.datetime | None = None):
    """Fail any run stuck in 'queued'/'running' longer than the deadline (worker
    crash, lost job). Returns the list of reaped run ids. Idempotent."""
    from apps.server.models import WebRun
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(seconds=max_running_seconds)
    reaped = []
    rows = db.query(WebRun).filter(WebRun.status.in_(("queued", "running"))).all()
    for run in rows:
        started = run.started_at or run.created_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=dt.timezone.utc)
        if started < cutoff:
            run.status = "failed"
            run.error = (f"run exceeded the maximum wall-clock budget "
                         f"({max_running_seconds}s) — reaped as stale")
            run.finished_at = now
            reaped.append(run.id)
    if reaped:
        db.commit()
    return reaped


# --------------------------------------------------------------------------- #
# Metrics snapshot
# --------------------------------------------------------------------------- #

def collect_metrics(db) -> dict:
    """Counts for /metrics: runs by status, totals, error rate, queue depth."""
    from sqlalchemy import func
    from apps.server.models import WebRun
    by_status = dict(db.query(WebRun.status, func.count(WebRun.id))
                     .group_by(WebRun.status).all())
    total = sum(by_status.values())
    failed = by_status.get("failed", 0)
    scored = by_status.get("scored", 0)
    finished = failed + scored
    return {
        "runs_total": total,
        "runs_by_status": by_status,
        "runs_queued": by_status.get("queued", 0),
        "runs_running": by_status.get("running", 0),
        "runs_scored": scored,
        "runs_failed": failed,
        "error_rate": round(failed / finished, 4) if finished else 0.0,
    }


def prometheus_text(metrics: dict) -> str:
    """Render the metrics snapshot as Prometheus text-exposition format."""
    lines = [
        "# HELP xodexa_runs_total Total benchmark runs recorded.",
        "# TYPE xodexa_runs_total counter",
        f"xodexa_runs_total {metrics['runs_total']}",
        "# HELP xodexa_runs_state Runs by state.",
        "# TYPE xodexa_runs_state gauge",
    ]
    for state in ("queued", "running", "scored", "failed"):
        lines.append(f'xodexa_runs_state{{state="{state}"}} '
                     f'{metrics["runs_by_status"].get(state, 0)}')
    lines += [
        "# HELP xodexa_error_rate Fraction of finished runs that failed.",
        "# TYPE xodexa_error_rate gauge",
        f"xodexa_error_rate {metrics['error_rate']}",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Structured logging
# --------------------------------------------------------------------------- #

class JsonLogFormatter(logging.Formatter):
    """One JSON object per log line, with any `extra={...}` fields merged in, so logs
    are queryable and a run_id/trace_id can correlate across services."""
    _STD = set(logging.makeLogRecord({}).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": dt.datetime.fromtimestamp(record.created, dt.timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in self._STD and not k.startswith("_"):
                payload[k] = v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_json_logging(level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root handler (idempotent)."""
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        h = logging.StreamHandler()
        root.addHandler(h)
    for h in root.handlers:
        h.setFormatter(JsonLogFormatter())
