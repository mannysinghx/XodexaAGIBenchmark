"""
apps.worker.worker
====================
RQ worker entrypoint. Run:  python -m apps.worker.worker
(or in docker-compose as the `worker` service). Requires REDIS_URL.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))

from redis import Redis  # noqa: E402
from rq import Queue, Worker  # noqa: E402

from apps.server.config import get_settings  # noqa: E402
from apps.server.db import init_db  # noqa: E402


def _reap_once():
    """Fail runs stuck past the wall-clock budget (crash/lost job). Best-effort."""
    import logging
    from apps.server.db import session
    from apps.server.runtime import reap_stale_runs
    s = get_settings()
    db = session()
    try:
        reaped = reap_stale_runs(db, max_running_seconds=s.max_run_seconds)
        if reaped:
            logging.getLogger("xodexa.reaper").warning(
                "reaped %d stale run(s): %s", len(reaped), reaped)
    finally:
        db.close()


def main():
    import logging
    s = get_settings()
    if s.json_logs:
        from apps.server.runtime import configure_json_logging
        configure_json_logging(logging.INFO)
    else:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not s.redis_url:
        raise SystemExit("REDIS_URL is required to run the worker")
    init_db()
    _reap_once()  # clean up anything a previous worker crash left 'running'
    conn = Redis.from_url(s.redis_url)
    q = Queue("xodexa", connection=conn)
    print(f"[xodexa-worker] listening on 'xodexa' @ {s.redis_url}")
    # with_scheduler=True lets RQ Retry backoffs and any scheduled reaps fire.
    Worker([q], connection=conn).work(with_scheduler=True)


if __name__ == "__main__":
    main()
