"""
apps.server.security
======================
Auth + secret-handling primitives, dependency-light:

  * Passwords  — stdlib ``hashlib.scrypt`` (salted), constant-time verify.
  * Sessions   — opaque random cookie token; only its SHA-256 is stored in the DB.
  * Provider keys — Fernet symmetric encryption (key from ``KEY_ENCRYPTION_KEY``).
  * CSRF       — double-submit token bound to the session via HMAC.
  * FastAPI deps — ``current_user`` / ``require_user`` / ``require_verified``.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import secrets

from cryptography.fernet import Fernet, InvalidToken

from apps.server.config import get_settings
from apps.server import models

_settings = get_settings()


# --------------------------------------------------------------------------- #
# Passwords (scrypt)
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, hash_hex = stored.split("$", 2)
        if algo != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Provider-key encryption (Fernet)
# --------------------------------------------------------------------------- #
def _fernet() -> Fernet:
    key = _settings.key_encryption_key
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)
    # Dev fallback: derive a stable key from the session secret. NOT for production —
    # rotating the secret makes stored ciphertext undecryptable. Set KEY_ENCRYPTION_KEY.
    derived = base64.urlsafe_b64encode(hashlib.sha256(
        ("kek:" + _settings.session_secret).encode()).digest())
    return Fernet(derived)


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_secret(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as e:  # pragma: no cover
        raise ValueError("could not decrypt stored credential (key rotated?)") from e


def generate_fernet_key() -> str:
    """Helper for ops: print a fresh KEY_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode()


# --------------------------------------------------------------------------- #
# Sessions + CSRF
# --------------------------------------------------------------------------- #
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> tuple[str, str]:
    """Returns (cookie_token, token_hash). Only the hash is persisted."""
    tok = secrets.token_urlsafe(32)
    return tok, _hash_token(tok)


def csrf_for(token: str) -> str:
    return hmac.new(_settings.session_secret.encode(), token.encode(),
                    hashlib.sha256).hexdigest()


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def session_expiry() -> dt.datetime:
    return now() + dt.timedelta(hours=_settings.session_ttl_hours)


# --------------------------------------------------------------------------- #
# FastAPI dependencies
# --------------------------------------------------------------------------- #
def _aware(d: dt.datetime) -> dt.datetime:
    # SQLite may return naive datetimes; treat them as UTC for comparison.
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def current_user(request, db) -> "models.User | None":
    from apps.server.models import SessionRow, User  # local import (mapper ready)
    tok = request.cookies.get(_settings.cookie_name)
    if not tok:
        return None
    row = db.query(SessionRow).filter_by(token_hash=_hash_token(tok)).first()
    if not row or row.revoked_at is not None:
        return None
    if _aware(row.expires_at) < now():
        return None
    request.state.session_token = tok  # so handlers can compute CSRF
    return db.get(User, row.user_id)
