"""
xodexa.crypto
===============
The cryptographic primitives behind Xodexa AGI Benchmark's trust model.

Everything here is intentionally small and auditable. It provides exactly four
guarantees and nothing more (see ANALYSIS.md §3.1 for what these do NOT prove):

  1. Identity   — Ed25519 keypairs identify the central server and each runner.
  2. Integrity  — detached signatures over canonical JSON prove a document was
                  not altered after signing.
  3. Ordering   — a hash chain over an event log makes silent post-hoc edits
                  detectable (any change breaks every subsequent link).
  4. Freshness  — server nonces + timestamps bound a run to a single challenge,
                  enabling replay/duplicate detection centrally.

Canonical JSON (sorted keys, no whitespace, UTF-8) is used everywhere so that
hashing and signing are deterministic across machines.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


# --------------------------------------------------------------------------- #
# Canonical serialization + hashing
# --------------------------------------------------------------------------- #

def canonical(obj) -> bytes:
    """Deterministic JSON encoding used for all hashing and signing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data) -> str:
    if not isinstance(data, (bytes, bytearray)):
        data = canonical(data)
    return hashlib.sha256(data).hexdigest()


def b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


# --------------------------------------------------------------------------- #
# Identity keys
# --------------------------------------------------------------------------- #

@dataclass
class KeyPair:
    """An Ed25519 identity. `priv_b64` is secret; `pub_b64` is shareable."""
    priv_b64: str
    pub_b64: str

    @staticmethod
    def generate() -> "KeyPair":
        sk = Ed25519PrivateKey.generate()
        raw_priv = sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        raw_pub = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return KeyPair(b64e(raw_priv), b64e(raw_pub))

    def _sk(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(b64d(self.priv_b64))

    def sign(self, payload) -> str:
        """Return a base64 detached signature over canonical(payload)."""
        return b64e(self._sk().sign(canonical(payload)))


def verify(pub_b64: str, payload, signature_b64: str) -> bool:
    """True iff `signature_b64` is a valid Ed25519 signature over payload."""
    try:
        pk = Ed25519PublicKey.from_public_bytes(b64d(pub_b64))
        pk.verify(b64d(signature_b64), canonical(payload))
        return True
    except (InvalidSignature, ValueError):
        return False


def fingerprint(pub_b64: str) -> str:
    """Short stable identifier for a public key (for UI / logs)."""
    return "k_" + sha256_hex(b64d(pub_b64))[:16]


# --------------------------------------------------------------------------- #
# Hash-chained, tamper-evident event log
# --------------------------------------------------------------------------- #

GENESIS = "0" * 64


class HashChain:
    """
    Append-only log where each entry commits to the previous entry's hash:

        h_i = SHA256( h_{i-1} || canonical(event_i) )

    Editing, reordering, inserting, or dropping any event changes `head()` and
    every hash after the touched point — so central verification can detect it by
    recomputing the chain from the recorded events.
    """

    def __init__(self):
        self.entries: list[dict] = []
        self._head = GENESIS

    def append(self, kind: str, data: dict) -> str:
        event = {"seq": len(self.entries), "ts": time.time(), "kind": kind, "data": data}
        link = sha256_hex((self._head + canonical(event).decode("utf-8")).encode("utf-8"))
        self._head = link
        self.entries.append({"event": event, "hash": link, "prev": self._prev_of(link)})
        return link

    def _prev_of(self, link):
        # prev pointer for the entry we just created
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def head(self) -> str:
        return self._head

    def export(self) -> list[dict]:
        return self.entries

    @staticmethod
    def verify(entries: list[dict]) -> tuple[bool, str]:
        """Recompute the chain; return (ok, head_or_error)."""
        prev = GENESIS
        for i, entry in enumerate(entries):
            event = entry["event"]
            if event.get("seq") != i:
                return False, f"seq mismatch at index {i}"
            link = sha256_hex((prev + canonical(event).decode("utf-8")).encode("utf-8"))
            if link != entry.get("hash"):
                return False, f"broken link at index {i}"
            prev = link
        return True, prev
