"""
apps.server.ratelimit
========================
A rate limiter that survives more than one server process. The old in-memory bucket
(deps._BUCKET) resets on restart and is per-process, so behind >1 replica an attacker
gets N× the limit. This uses a Redis sliding window when REDIS_URL is set, and falls
back to the in-memory bucket in single-process dev. Same call signature either way.
"""

from __future__ import annotations

import threading
import time

from apps.server.config import get_settings

_settings = get_settings()
_lock = threading.Lock()
_MEM: dict[str, list[float]] = {}
_redis = None
_redis_tried = False


def _get_redis():
    global _redis, _redis_tried
    if _redis_tried:
        return _redis
    _redis_tried = True
    if _settings.redis_url:
        try:
            from redis import Redis
            _redis = Redis.from_url(_settings.redis_url)
            _redis.ping()
        except Exception:  # noqa: BLE001 — degrade to in-memory rather than fail auth
            _redis = None
    return _redis


def allow(bucket_key: str, limit: int, window: float) -> bool:
    """Return True if a hit is allowed under `limit` per `window` seconds for this
    key; records the hit when allowed. Distributed via Redis when available."""
    now = time.time()
    r = _get_redis()
    if r is not None:
        try:
            zkey = f"rl:{bucket_key}"
            pipe = r.pipeline()
            pipe.zremrangebyscore(zkey, 0, now - window)
            pipe.zcard(zkey)
            pipe.zadd(zkey, {f"{now}:{id(object())}": now})
            pipe.expire(zkey, int(window) + 1)
            _, count, _, _ = pipe.execute()
            if count >= limit:
                # over limit: undo the add we just made so we don't leak the slot
                r.zpopmax(zkey)
                return False
            return True
        except Exception:  # noqa: BLE001 — Redis blip: fall through to memory
            pass
    with _lock:
        hits = [t for t in _MEM.get(bucket_key, []) if now - t < window]
        if len(hits) >= limit:
            _MEM[bucket_key] = hits
            return False
        hits.append(now)
        _MEM[bucket_key] = hits
        return True


def reset() -> None:
    """Test helper: clear the in-memory window."""
    with _lock:
        _MEM.clear()
