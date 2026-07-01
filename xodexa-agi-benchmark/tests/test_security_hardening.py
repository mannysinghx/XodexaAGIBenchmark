"""Tests for Phase-1d security hardening: answer-key at-rest encryption and the
production dev-secret boot guard."""

import pytest

from apps.server.config import Settings
from apps.server.security import (
    decrypt_answer_field,
    encrypt_answer_field,
)


# --------------------------------------------------------------------------- #
# Answer-key at-rest encryption
# --------------------------------------------------------------------------- #

def test_string_roundtrip():
    enc = encrypt_answer_field("8008")
    assert enc.startswith("encv1:") and "8008" not in enc
    assert decrypt_answer_field(enc) == "8008"


def test_dict_roundtrip_via_parse_json():
    grader = {"type": "numeric", "target": 8.0, "tolerance": 0.01}
    enc = encrypt_answer_field(grader)
    assert isinstance(enc, str) and enc.startswith("encv1:")
    assert "numeric" not in enc  # ciphertext leaks nothing
    assert decrypt_answer_field(enc, parse_json=True) == grader


def test_none_passes_through():
    assert encrypt_answer_field(None) is None
    assert decrypt_answer_field(None) is None


def test_legacy_plaintext_rows_still_readable():
    # Rows written before encryption landed hold plaintext / raw dicts.
    assert decrypt_answer_field("plain old answer") == "plain old answer"
    legacy_grader = {"type": "exact", "accept": ["paris"]}
    assert decrypt_answer_field(legacy_grader, parse_json=True) == legacy_grader


def test_ciphertext_differs_per_call_but_decrypts_identically():
    a, b = encrypt_answer_field("secret"), encrypt_answer_field("secret")
    assert a != b  # Fernet nonce
    assert decrypt_answer_field(a) == decrypt_answer_field(b) == "secret"


# --------------------------------------------------------------------------- #
# Production boot guard
# --------------------------------------------------------------------------- #

def _prod_settings(monkeypatch, **overrides):
    monkeypatch.setenv("XODEXA_PRODUCTION", "1")
    s = Settings()
    # Instance attributes shadow the import-time class attributes.
    s.session_secret = overrides.get("session_secret", "dev-insecure-session-secret")
    s.key_encryption_key = overrides.get("key_encryption_key", "")
    s.report_signing_key = overrides.get("report_signing_key", "")
    return s


def test_production_with_dev_defaults_refuses_to_boot(monkeypatch):
    s = _prod_settings(monkeypatch)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        s.assert_production_safe()


def test_production_with_real_secrets_boots(monkeypatch):
    s = _prod_settings(
        monkeypatch,
        session_secret="a-real-rotated-secret",
        key_encryption_key="Zml4ZWQtand0LXRlc3Qta2V5LWZpeGVkLWp3dC10ZXN0LWtleQ==",
        report_signing_key="c2lnbmluZy1rZXktc2lnbmluZy1rZXktc2lnbmluZy0hIQ==",
    )
    s.assert_production_safe()  # must not raise


def test_dev_mode_never_blocks(monkeypatch):
    monkeypatch.delenv("XODEXA_PRODUCTION", raising=False)
    monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    s = Settings()
    s.session_secret = "dev-insecure-session-secret"
    s.key_encryption_key = ""
    s.report_signing_key = ""
    s.assert_production_safe()  # dev: allowed


def test_managed_host_detection_counts_as_production(monkeypatch):
    monkeypatch.delenv("XODEXA_PRODUCTION", raising=False)
    monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "xodexa.up.railway.app")
    s = Settings()
    s.session_secret = "dev-insecure-session-secret"
    with pytest.raises(RuntimeError):
        s.assert_production_safe()
