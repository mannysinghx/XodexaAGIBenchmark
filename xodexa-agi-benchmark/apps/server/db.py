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

import logging  # noqa: E402

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.orm import declarative_base, sessionmaker, Session  # noqa: E402

_log = logging.getLogger("xodexa.db")

from apps.server.config import get_settings  # noqa: E402

_settings = get_settings()

def _normalize_db_url(url: str) -> str:
    """Most hosts (Railway, Neon, Heroku) inject a `postgres://` / `postgresql://` URL,
    but our driver is psycopg3 → force the `postgresql+psycopg://` SQLAlchemy scheme so
    the platform's auto-provided DATABASE_URL works without manual editing."""
    if url.startswith("postgresql+"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    return url


_db_url = _normalize_db_url(_settings.database_url)
_connect_args = {}
if _db_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(_db_url, pool_pre_ping=True,
                       future=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                            class_=Session, future=True)
Base = declarative_base()


def _sync_added_columns() -> None:
    """Lightweight additive migration: create_all() makes new TABLES but never adds new
    COLUMNS to a table that already exists. For each mapped table that's already present,
    ALTER TABLE ADD COLUMN any NULLABLE column the DB is missing (e.g. the expanded
    per-task trace fields on web_run_responses). Idempotent and portable (sqlite +
    postgres both support ADD COLUMN); only nullable columns are added so existing rows
    stay valid. Non-additive changes still need a real migration."""
    insp = inspect(engine)
    present = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in present:
            continue  # create_all already made it with the full, current shape
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have or not col.nullable:
                continue
            ddl = (f'ALTER TABLE {table.name} '
                   f'ADD COLUMN {col.name} {col.type.compile(dialect=engine.dialect)}')
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                _log.info("db migration: added %s.%s", table.name, col.name)
            except Exception as e:  # noqa: BLE001 — never block startup on one column
                _log.warning("db migration: could not add %s.%s: %s",
                             table.name, col.name, e)


def init_db() -> None:
    """Create all tables, then add any newly-introduced nullable columns (idempotent).
    Called on app + worker startup."""
    from apps.server import models  # noqa: F401  (register mappers)
    Base.metadata.create_all(bind=engine)
    _sync_added_columns()


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
