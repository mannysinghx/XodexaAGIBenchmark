#!/usr/bin/env python3
"""
gen_secrets.py — mint the production secrets the server now REQUIRES to boot.

Since the Phase-1d hardening, a managed deployment (Railway/Render/XODEXA_PRODUCTION=1)
refuses to start on dev-default secrets, because those would mean forgeable sessions
and a derivable key for every encrypted credential and answer-key column. This prints
three freshly-generated secrets to paste into your host's env-var settings (never into
the repo):

  SESSION_SECRET       — signs sessions + CSRF tokens (also the KEK/root-signer fallback
                         seed, which is exactly why it must not be the dev default).
  KEY_ENCRYPTION_KEY   — Fernet key encrypting provider credentials + answer keys at rest.
  REPORT_SIGNING_KEY   — stable Ed25519 private key the server signs reports with, so the
                         verification appendix anchors to one published public key.

    python scripts/gen_secrets.py            # human-readable
    python scripts/gen_secrets.py --dotenv   # .env format to append to a local .env
"""

from __future__ import annotations

import argparse
import base64
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages"))

from cryptography.fernet import Fernet  # noqa: E402
from xodexa.crypto import KeyPair  # noqa: E402


def mint() -> dict[str, str]:
    return {
        # 48 random bytes, urlsafe — plenty for HMAC/session signing.
        "SESSION_SECRET": secrets.token_urlsafe(48),
        # Fernet's own 32-byte urlsafe-base64 key.
        "KEY_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        # Ed25519 private key (base64 raw 32 bytes), as report_signer expects.
        "REPORT_SIGNING_KEY": KeyPair.generate().priv_b64,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint production secrets for Xodexa.")
    ap.add_argument("--dotenv", action="store_true", help="print in KEY=VALUE .env form")
    args = ap.parse_args()

    s = mint()
    # Sanity: the Ed25519 key round-trips (fail loudly rather than emit a bad key).
    pub = KeyPair.from_private_b64(s["REPORT_SIGNING_KEY"]).pub_b64
    assert base64.b64decode(pub)

    if args.dotenv:
        for k, v in s.items():
            print(f"{k}={v}")
    else:
        print("Set these THREE env vars on your host (Render/Railway dashboard),")
        print("NOT in the repo. They are required for production boot.\n")
        for k, v in s.items():
            print(f"  {k}={v}")
        print(f"\n  (report public key derived from REPORT_SIGNING_KEY: {pub})")
        print("\nRotate SESSION_SECRET/KEY_ENCRYPTION_KEY only with care: rotating the")
        print("KEK makes already-encrypted credentials + answer keys undecryptable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
