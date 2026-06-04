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


def main():
    import logging
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = get_settings()
    if not s.redis_url:
        raise SystemExit("REDIS_URL is required to run the worker")
    init_db()
    conn = Redis.from_url(s.redis_url)
    q = Queue("xodexa", connection=conn)
    print(f"[xodexa-worker] listening on 'xodexa' @ {s.redis_url}")
    Worker([q], connection=conn).work(with_scheduler=False)


if __name__ == "__main__":
    main()
