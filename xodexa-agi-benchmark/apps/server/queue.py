"""
apps.server.queue
===================
Enqueue a benchmark run. With Redis configured it goes to an RQ worker; in dev (no
Redis) it runs in a background thread so the HTTP request still returns immediately.
Use-once keys travel only in the job payload (Redis/in-memory), never the database.
"""

from __future__ import annotations

from apps.server.config import get_settings
from apps.server.runtime import run_timeout_seconds

_settings = get_settings()


def enqueue_run(run_id: str, inline_key: str | None = None,
                inline_base_url: str | None = None, n_tasks: int = 40) -> str:
    if _settings.redis_url and not _settings.run_inline:
        from redis import Redis
        from rq import Queue, Retry
        q = Queue("xodexa", connection=Redis.from_url(_settings.redis_url))
        # Dynamic budget instead of a flat 3600 s (200-task runs on slow models blew
        # through it); capped by MAX_RUN_SECONDS. execute_run is idempotent (it resumes
        # from persisted per-task traces), so an RQ retry after a worker crash is safe.
        timeout = min(run_timeout_seconds(n_tasks), _settings.max_run_seconds)
        job = q.enqueue("apps.worker.run_job.execute_run", run_id, inline_key,
                        inline_base_url, job_timeout=timeout, retry=Retry(max=1))
        return job.id
    # dev fallback: background thread
    import threading
    from apps.worker.run_job import execute_run
    threading.Thread(target=execute_run, args=(run_id, inline_key, inline_base_url),
                     daemon=True).start()
    return "inline"
