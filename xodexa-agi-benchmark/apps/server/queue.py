"""
apps.server.queue
===================
Enqueue a benchmark run. With Redis configured it goes to an RQ worker; in dev (no
Redis) it runs in a background thread so the HTTP request still returns immediately.
Use-once keys travel only in the job payload (Redis/in-memory), never the database.
"""

from __future__ import annotations

from apps.server.config import get_settings

_settings = get_settings()


def enqueue_run(run_id: str, inline_key: str | None = None,
                inline_base_url: str | None = None) -> str:
    if _settings.redis_url and not _settings.run_inline:
        from redis import Redis
        from rq import Queue
        q = Queue("xodexa", connection=Redis.from_url(_settings.redis_url))
        job = q.enqueue("apps.worker.run_job.execute_run", run_id, inline_key,
                        inline_base_url, job_timeout=3600)
        return job.id
    # dev fallback: background thread
    import threading
    from apps.worker.run_job import execute_run
    threading.Thread(target=execute_run, args=(run_id, inline_key, inline_base_url),
                     daemon=True).start()
    return "inline"
