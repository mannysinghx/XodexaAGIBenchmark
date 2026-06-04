"""
xodexa.audit
==============
Append-only audit log for every grader decision (deterministic and semantic).
Every record is immutable once written. The log is used for human review,
compliance, and tamper-detection (via hash-chained records, same as crypto.HashChain).

Security requirement: audit records must never contain:
  - raw canary values
  - private prompt text
  - official benchmark answer keys
  - PII from task inputs

Records ARE allowed to contain:
  - task_id
  - run_id
  - task_family + subdomain
  - grader label
  - severity + multiplier
  - scores (not raw inputs)
  - evidence from model response (not from hidden benchmark data)
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #

@dataclass
class AuditRecord:
    """One immutable grader decision record."""
    record_id: str          # UUID for this record
    run_id: str             # the benchmark run this record belongs to
    task_id: str            # the task that was graded
    task_family: str
    subdomain: str
    grader_type: str        # "deterministic" | "llm_judge"
    label: str              # grader output label
    severity: str           # "critical" | "high" | "medium" | "low" | "none"
    multiplier: float       # deterministic severity multiplier applied
    scores: dict            # all numeric scores from the grader
    evidence: list[str]     # evidence from the model response (NOT from private content)
    human_review_required: bool
    created_at: str         # ISO-8601 UTC timestamp
    chain_hash: str         # SHA-256 of (prev_hash + canonical(record_data))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _canonical(data: dict) -> str:
    """Stable JSON serialization (sorted keys) for hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _compute_chain_hash(prev_hash: str, record_data: dict) -> str:
    """Hash-chain: SHA256(prev_hash + canonical(record_data))."""
    payload = prev_hash + _canonical(record_data)
    return _sha256(payload)


def _record_data_for_hash(record: AuditRecord) -> dict:
    """Subset of record fields used for the chain hash (excludes chain_hash itself)."""
    return {
        "record_id": record.record_id,
        "run_id": record.run_id,
        "task_id": record.task_id,
        "task_family": record.task_family,
        "subdomain": record.subdomain,
        "grader_type": record.grader_type,
        "label": record.label,
        "severity": record.severity,
        "multiplier": record.multiplier,
        "scores": record.scores,
        "human_review_required": record.human_review_required,
        "created_at": record.created_at,
    }


# --------------------------------------------------------------------------- #
# AuditLog
# --------------------------------------------------------------------------- #

_GENESIS_HASH = "0" * 64  # initial prev_hash for the first record


class AuditLog:
    """Append-only, hash-chained audit log stored in memory.

    The chain can be exported to JSONL and verified for tampering.
    """

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._prev_hash: str = _GENESIS_HASH

    # ---- write side ----------------------------------------------------------

    def append(self, record: AuditRecord) -> None:
        """Append an immutable record. Computes and sets chain_hash."""
        data = _record_data_for_hash(record)
        record.chain_hash = _compute_chain_hash(self._prev_hash, data)
        self._prev_hash = record.chain_hash
        self._records.append(record)

    def new_record(
        self,
        run_id: str,
        task_id: str,
        task_family: str,
        subdomain: str,
        grader_type: str,
        label: str,
        severity: str,
        multiplier: float,
        scores: dict,
        evidence: list[str],
        human_review_required: bool,
    ) -> AuditRecord:
        """Convenience factory: build a record with a new UUID and current timestamp,
        then append it to the log. Returns the appended record."""
        record = AuditRecord(
            record_id=str(uuid.uuid4()),
            run_id=run_id,
            task_id=task_id,
            task_family=task_family,
            subdomain=subdomain,
            grader_type=grader_type,
            label=label,
            severity=severity,
            multiplier=multiplier,
            scores=scores,
            evidence=evidence,
            human_review_required=human_review_required,
            created_at=_iso_now(),
            chain_hash="",  # computed in append()
        )
        self.append(record)
        return record

    # ---- read side -----------------------------------------------------------

    def export(self) -> list[dict]:
        """Export all records as a list of plain dicts."""
        return [asdict(r) for r in self._records]

    def to_jsonl(self) -> str:
        """Serialize all records as newline-delimited JSON."""
        return "\n".join(
            json.dumps(asdict(r), sort_keys=True, default=str)
            for r in self._records
        )

    def get_human_review_queue(self) -> list[AuditRecord]:
        """Return records that require human review."""
        return [r for r in self._records if r.human_review_required]

    def verify_chain(self) -> bool:
        """Re-compute every record's chain hash and verify integrity.

        Returns True if the chain is intact, False if any record was tampered with.
        """
        prev = _GENESIS_HASH
        for record in self._records:
            data = _record_data_for_hash(record)
            expected = _compute_chain_hash(prev, data)
            if record.chain_hash != expected:
                return False
            prev = record.chain_hash
        return True

    def __len__(self) -> int:
        return len(self._records)
