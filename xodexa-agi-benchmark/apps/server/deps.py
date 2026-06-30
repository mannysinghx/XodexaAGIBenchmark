"""
apps.server.deps
==================
Shared FastAPI dependencies + helpers: auth gates, CSRF, audit logging, per-user
quota enforcement (anti-runaway), and a tiny in-memory rate limiter for auth routes.
"""

from __future__ import annotations

import datetime as dt
import time

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from apps.server import security
from apps.server.config import get_settings
from apps.server.db import get_db
from apps.server.models import AuditLog, User, UsageQuota, WebRun

_settings = get_settings()


# --- auth gates ----------------------------------------------------------------
def get_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return security.current_user(request, db)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    u = security.current_user(request, db)
    if not u:
        raise HTTPException(401, "authentication required")
    return u


def require_verified(request: Request, db: Session = Depends(get_db)) -> User:
    u = require_user(request, db)
    if not u.email_verified:
        raise HTTPException(403, "email not verified")
    return u


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    u = require_user(request, db)
    if not u.is_admin:
        raise HTTPException(403, "admin only")
    return u


# --- CSRF (double-submit, bound to session via HMAC) ---------------------------
def csrf_protect(request: Request):
    tok = request.cookies.get(_settings.cookie_name)
    if not tok:
        raise HTTPException(401, "authentication required")
    header = request.headers.get("x-csrf-token", "")
    if not header or header != security.csrf_for(tok):
        raise HTTPException(403, "invalid CSRF token")


# --- audit ---------------------------------------------------------------------
def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else ""))


def audit(db: Session, request: Request, action: str, user_id: str | None = None,
          **meta) -> None:
    db.add(AuditLog(user_id=user_id, action=action, meta=meta, ip=client_ip(request)))
    db.commit()


# --- quotas (anti-runaway) -----------------------------------------------------
def _today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def get_quota(db: Session, user_id: str) -> UsageQuota:
    q = db.query(UsageQuota).filter_by(user_id=user_id, day=_today()).first()
    if not q:
        q = UsageQuota(user_id=user_id, day=_today())
        db.add(q)
        db.commit()
        db.refresh(q)
    return q


def enforce_run_quota(db: Session, user_id: str, n_tasks: int) -> None:
    if not (_settings.min_tasks_per_run <= n_tasks <= _settings.max_tasks_per_run):
        raise HTTPException(422, f"n_tasks must be between {_settings.min_tasks_per_run} "
                                 f"and {_settings.max_tasks_per_run}")
    active = (db.query(WebRun)
              .filter(WebRun.user_id == user_id,
                      WebRun.status.in_(("queued", "running")))
              .count())
    if active >= _settings.max_concurrent_runs:
        raise HTTPException(429, "a run is already in progress; wait for it to finish")
    q = get_quota(db, user_id)
    if q.runs_started >= _settings.max_runs_per_day:
        raise HTTPException(429, f"daily run limit reached ({_settings.max_runs_per_day})")
    if q.tasks_run + n_tasks > _settings.max_tasks_per_day:
        raise HTTPException(429, f"daily task limit reached ({_settings.max_tasks_per_day})")


def record_run_started(db: Session, user_id: str, n_tasks: int) -> None:
    q = get_quota(db, user_id)
    q.runs_started += 1
    q.tasks_run += n_tasks
    db.commit()


# --- simple in-memory rate limiter for auth routes -----------------------------
_BUCKET: dict[str, list[float]] = {}


def rate_limit(request: Request, key: str, limit: int = 5, window: float = 60.0):
    ip = client_ip(request) or "anon"
    bkey = f"{key}:{ip}"
    now = time.time()
    hits = [t for t in _BUCKET.get(bkey, []) if now - t < window]
    if len(hits) >= limit:
        raise HTTPException(429, "too many requests; slow down")
    hits.append(now)
    _BUCKET[bkey] = hits
