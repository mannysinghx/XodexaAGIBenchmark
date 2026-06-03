"""
apps.server.db
================
SQLAlchemy engine + session. Uses portable column types (see models.py) so the exact
same ORM runs on SQLite (zero-infra dev) and PostgreSQL (production / docker-compose).
The app owns the schema via ``Base.metadata.create_all`` on startup.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the xodexa engine importable wherever this app runs (web + worker).
_PKGS = Path(__file__).resolve().parents[2] / "packages"
if str(_PKGS) not in sys.path:
    sys.path.insert(0, str(_PKGS))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import declarative_base, sessionmaker, Session  # noqa: E402

from apps.server.config import get_settings  # noqa: E402

_settings = get_settings()

_connect_args = {}
if _settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(_settings.database_url, pool_pre_ping=True,
                       future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                            class_=Session, future=True)
Base = declarative_base()


def init_db() -> None:
    """Create all tables (idempotent). Called on app + worker startup."""
    from apps.server import models  # noqa: F401  (register mappers)
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def session() -> Session:
    """A standalone session (worker / scripts)."""
    return SessionLocal()
