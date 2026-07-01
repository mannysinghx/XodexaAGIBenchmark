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
    """The comprehensive per-task trace — the repository row. One per (run, task): the
    exact prompt sent, the model's full reasoning/answer, its stated confidence, real
    token usage (prompt/completion/total), the grader spec + expected answer, the central
    score/verdict, timing, and any provider error. Contains answer keys, so it is
    OWNER/ADMIN-ONLY — never served on a public endpoint."""
    __tablename__ = "web_run_responses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("web_runs.id", ondelete="CASCADE"),
                                        index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False)
    family: Mapped[str] = mapped_column(String(32))
    # --- denormalized run context (so the repository is queryable on its own) ---
    model_name: Mapped[str | None] = mapped_column(String(128), index=True)
    provider: Mapped[str | None] = mapped_column(String(32))
    subdomain: Mapped[str | None] = mapped_column(String(64))
    difficulty: Mapped[float | None] = mapped_column(Float)
    visibility: Mapped[str | None] = mapped_column(String(16))
    # --- the question ---
    prompt: Mapped[str | None] = mapped_column(Text)            # exact text sent to the model
    expected_answer_type: Mapped[str | None] = mapped_column(String(32))
    grader_type: Mapped[str | None] = mapped_column(String(32))
    grader_json: Mapped[dict | None] = mapped_column(JSON)      # full deterministic grader spec
    expected_answer: Mapped[str | None] = mapped_column(Text)
    canary: Mapped[str | None] = mapped_column(String(64))
    # --- the answer / reasoning ---
    output: Mapped[str | None] = mapped_column(Text)            # full model reasoning + answer
    output_sha256: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)     # model-stated confidence 0..1
    error: Mapped[str | None] = mapped_column(Text)             # provider error if unanswered
    # --- usage / timing ---
    latency_ms: Mapped[float | None] = mapped_column(Float)
    tokens: Mapped[int | None] = mapped_column(Integer)         # completion tokens (legacy field)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    # --- central score (filled after re-scoring; null for errored/unanswered tasks) ---
    category: Mapped[str | None] = mapped_column(String(32))
    awarded: Mapped[float | None] = mapped_column(Float)
    max_points: Mapped[float | None] = mapped_column(Float)
    verdict: Mapped[str | None] = mapped_column(String(64))
    # --- LLM safety judge (security families only; null when judge not configured) ---
    judge_label: Mapped[str | None] = mapped_column(String(48))
    judge_score: Mapped[float | None] = mapped_column(Float)        # 0-100 score_example()
    judge_confidence: Mapped[float | None] = mapped_column(Float)   # ensemble confidence 0..1
    judge_agreement: Mapped[float | None] = mapped_column(Float)    # majority fraction 0..1
    judge_review: Mapped[bool | None] = mapped_column(Boolean)      # routed to human review
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def as_trace(self) -> dict:
        """Serialize the full trace for API/JSONL export (the repository record)."""
        return {
            "run_id": self.run_id, "task_id": self.task_id,
            "model_name": self.model_name, "provider": self.provider,
            "family": self.family, "subdomain": self.subdomain,
            "category": self.category, "difficulty": self.difficulty,
            "visibility": self.visibility,
            "prompt": self.prompt, "expected_answer_type": self.expected_answer_type,
            "grader_type": self.grader_type, "grader": self.grader_json,
            "expected_answer": self.expected_answer, "canary": self.canary,
            "output": self.output, "output_sha256": self.output_sha256,
            "confidence": self.confidence, "error": self.error,
            "latency_ms": self.latency_ms,
            "tokens": {"prompt": self.prompt_tokens, "completion": self.completion_tokens,
                       "total": self.total_tokens, "completion_legacy": self.tokens},
            "score": {"awarded": self.awarded, "max": self.max_points,
                      "verdict": self.verdict},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


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
