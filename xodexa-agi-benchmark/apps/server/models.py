"""
apps.server.models
=====================
ORM models — the Postgres source of truth for the product (auth, per-user provider
credentials, web-initiated runs, every per-task data point, signed reports, audit log,
quotas). Portable column types so the same schema runs on SQLite (dev) and Postgres.

Security notes:
  * Passwords: only ``password_hash`` (scrypt) is stored — never plaintext.
  * Provider keys: ``key_encrypted`` is Fernet ciphertext; ``key_last4`` is the only
    plaintext fragment exposed. NULL when the user chose "use once" (never persisted).
  * Sessions: only a hash of the opaque cookie token is stored, so a DB leak can't
    resurrect live sessions.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, JSON,
                        LargeBinary, String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.server.db import Base


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users_app"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    credentials = relationship("ProviderCredential", back_populates="user",
                               cascade="all, delete-orphan")
    runs = relationship("WebRun", back_populates="user", cascade="all, delete-orphan")


class EmailVerification(Base):
    __tablename__ = "email_verifications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users_app.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionRow(Base):
    __tablename__ = "sessions_app"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users_app.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProviderCredential(Base):
    __tablename__ = "provider_credentials"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users_app.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(64), default="")
    key_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)  # NULL == use-once
    key_last4: Mapped[str] = mapped_column(String(8), default="")
    base_url: Mapped[str | None] = mapped_column(String(256))  # for openai-compatible/local
    status: Mapped[str] = mapped_column(String(16), default="unvalidated")  # validated|invalid
    validated_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user = relationship("User", back_populates="credentials")


class UserModel(Base):
    __tablename__ = "user_models"
    __table_args__ = (UniqueConstraint("user_id", "provider", "model_name"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users_app.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    validated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebRun(Base):
    __tablename__ = "web_runs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users_app.id", ondelete="CASCADE"))
    credential_id: Mapped[str | None] = mapped_column(String(32))  # null == use-once key
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    suite: Mapped[str] = mapped_column(String(64), default="xodexa-live")
    family: Mapped[str | None] = mapped_column(String(32))  # None == all families
    n_tasks: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), default="public")  # public|private
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|scored|failed
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    error: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    xodexa_score: Mapped[float | None] = mapped_column(Float)
    grade: Mapped[str | None] = mapped_column(String(48))
    agi_index: Mapped[float | None] = mapped_column(Float)
    agi_level: Mapped[int | None] = mapped_column(Integer)
    accuracy: Mapped[float | None] = mapped_column(Float)
    calibration_error: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    user = relationship("User", back_populates="runs")


class WebRunResponse(Base):
    __tablename__ = "web_run_responses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("web_runs.id", ondelete="CASCADE"))
    task_id: Mapped[str] = mapped_column(String(96), nullable=False)
    family: Mapped[str] = mapped_column(String(32))
    output: Mapped[str | None] = mapped_column(Text)
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    tokens: Mapped[int | None] = mapped_column(Integer)


class WebRunItemScore(Base):
    __tablename__ = "web_run_item_scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("web_runs.id", ondelete="CASCADE"))
    task_id: Mapped[str] = mapped_column(String(96), nullable=False)
    family: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(32))
    awarded: Mapped[float] = mapped_column(Float)
    max_points: Mapped[float] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(64))
    difficulty: Mapped[float | None] = mapped_column(Float)


class RunEvent(Base):
    __tablename__ = "run_events_app"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("web_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    __table_args__ = (UniqueConstraint("run_id", "seq"),)


class Report(Base):
    __tablename__ = "reports_app"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("web_runs.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users_app.id", ondelete="CASCADE"))
    report_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    xodexa_score: Mapped[float | None] = mapped_column(Float)
    grade: Mapped[str | None] = mapped_column(String(48))
    agi_index: Mapped[float | None] = mapped_column(Float)
    agi_level: Mapped[int | None] = mapped_column(Integer)
    body_sha256: Mapped[str | None] = mapped_column(String(64))
    signer_pub: Mapped[str | None] = mapped_column(String(64))
    signature: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UsageQuota(Base):
    __tablename__ = "usage_quota"
    __table_args__ = (UniqueConstraint("user_id", "day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users_app.id", ondelete="CASCADE"))
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD (UTC)
    runs_started: Mapped[int] = mapped_column(Integer, default=0)
    tasks_run: Mapped[int] = mapped_column(Integer, default=0)
