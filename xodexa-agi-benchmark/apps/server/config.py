"""
apps.server.config
====================
Central settings, all from environment (12-factor). Safe local defaults so the app
boots for development without any secrets; production overrides via .env / Docker /
Vault. Secrets (SMTP password, key-encryption key, session secret) are NEVER hardcoded.
"""

from __future__ import annotations

import os
from functools import lru_cache


def _b(v: str | None, default: bool) -> bool:
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    # --- database ---
    # Default to a local SQLite file so the app runs with zero infra in dev; compose
    # sets DATABASE_URL to Postgres. The ORM uses portable types so both work.
    database_url: str = os.environ.get("DATABASE_URL", "sqlite:///./xodexa_app.db")

    # --- queue / worker ---
    redis_url: str = os.environ.get("REDIS_URL", "")  # empty -> inline execution (dev)
    run_inline: bool = _b(os.environ.get("RUN_INLINE"), False)

    # --- crypto / sessions ---
    # Fernet key for provider-credential encryption. If unset, a dev key is derived
    # (NOT for production — stored keys would not survive a restart's key rotation).
    key_encryption_key: str = os.environ.get("KEY_ENCRYPTION_KEY", "")
    # Stable Ed25519 private key (base64 raw, 32 bytes) the server signs reports with, so
    # the verification appendix is anchored to a PUBLISHED public key (GET /api/verification-key)
    # rather than a throwaway per-run key. If unset, a stable key is derived from
    # session_secret (fine for dev; set REPORT_SIGNING_KEY in prod so it survives a
    # secret rotation). Mint one with: python -c "from xodexa.crypto import KeyPair;print(KeyPair.generate().priv_b64)"
    report_signing_key: str = os.environ.get("REPORT_SIGNING_KEY", "")
    session_secret: str = os.environ.get("SESSION_SECRET", "dev-insecure-session-secret")
    session_ttl_hours: int = int(os.environ.get("SESSION_TTL_HOURS", "168"))  # 7d
    cookie_secure: bool = _b(os.environ.get("COOKIE_SECURE"), False)
    cookie_name: str = os.environ.get("SESSION_COOKIE", "xodexa_session")

    # --- email (privateemail.com by default) ---
    smtp_host: str = os.environ.get("SMTP_HOST", "mail.privateemail.com")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    mail_from: str = os.environ.get("MAIL_FROM", "info@xodexabenchmark.com")
    mail_from_name: str = os.environ.get("MAIL_FROM_NAME", "Xodexa AI Benchmark")

    # --- public URLs (verification links, CORS) ---
    # Auto-detect on common hosts (Render injects RENDER_EXTERNAL_URL) so verification
    # links work without manual config; PUBLIC_BASE_URL overrides when set.
    public_base_url: str = (
        os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("RENDER_EXTERNAL_URL")
        or (("https://" + os.environ["RAILWAY_PUBLIC_DOMAIN"])
            if os.environ.get("RAILWAY_PUBLIC_DOMAIN") else None)
        or "http://localhost:8000")
    cors_origins: list[str] = [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
    ]

    # --- legitimacy / anti-runaway quotas ---
    max_tasks_per_run: int = int(os.environ.get("MAX_TASKS_PER_RUN", "200"))
    min_tasks_per_run: int = int(os.environ.get("MIN_TASKS_PER_RUN", "5"))
    max_concurrent_runs: int = int(os.environ.get("MAX_CONCURRENT_RUNS", "1"))
    max_runs_per_day: int = int(os.environ.get("MAX_RUNS_PER_DAY", "10"))
    max_tasks_per_day: int = int(os.environ.get("MAX_TASKS_PER_DAY", "1000"))
    verification_ttl_hours: int = int(os.environ.get("VERIFICATION_TTL_HOURS", "24"))

    benchmark_version: str = os.environ.get("BENCHMARK_VERSION", "1.0.0")

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgres")

    @property
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
