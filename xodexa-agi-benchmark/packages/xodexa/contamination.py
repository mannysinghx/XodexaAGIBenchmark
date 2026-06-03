"""
xodexa.contamination
=======================
Contamination resistance is the moat (ANALYSIS.md §1.2): the hardest benchmark on
Earth is worthless the week its questions leak into a training set. This module is
the data-strategy subsystem, not a leaderboard afterthought.

Two jobs:

  1. **Build-time filtering** — score every candidate task's textual similarity against
     a reference corpus (known public benchmarks, the web, prior releases) and reject
     anything too close. Uses n-gram (token) overlap + character-shingle Jaccard +
     MinHash-style signatures. No heavy embedding model required for the MVP; the
     interface (``CorpusIndex.similarity``) is the seam where a real embedding index
     (FAISS / pgvector) drops in.

  2. **Run-time detection** — canary-echo detection, suspicious-perfect-score and
     timing-anomaly signals consumed by the central authority during re-scoring.

Everything is pure-Python + stdlib so it runs in the air-gapped pipeline.
"""

from __future__ import annotations

import re
from .crypto import sha256_hex

_WORD = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def ngrams(seq: list[str], n: int) -> set[tuple]:
    if len(seq) < n:
        return {tuple(seq)} if seq else set()
    return {tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)}


def char_shingles(text: str, k: int = 5) -> set[str]:
    t = re.sub(r"\s+", " ", (text or "").lower())
    if len(t) < k:
        return {t} if t else set()
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def ngram_overlap(text_a: str, text_b: str, n: int = 8) -> float:
    """Containment of a's n-grams in b (asymmetric — catches a being a substring of b)."""
    ga, gb = ngrams(tokens(text_a), n), ngrams(tokens(text_b), n)
    if not ga:
        return 0.0
    return len(ga & gb) / len(ga)


def minhash_signature(text: str, num_perm: int = 32, k: int = 5) -> list[int]:
    """A tiny MinHash signature over character shingles for fast near-dup detection."""
    sh = char_shingles(text, k)
    if not sh:
        return [0] * num_perm
    sig = []
    for p in range(num_perm):
        best = min(int(sha256_hex(f"{p}:{s}".encode())[:8], 16) for s in sh)
        sig.append(best)
    return sig


def signature_similarity(sig_a: list[int], sig_b: list[int]) -> float:
    if not sig_a or len(sig_a) != len(sig_b):
        return 0.0
    return sum(1 for x, y in zip(sig_a, sig_b) if x == y) / len(sig_a)


class CorpusIndex:
    """A reference corpus of strings we must NOT resemble (public benchmark items,
    crawled web snippets, prior public releases). Real deployments back this with an
    embedding/ANN index; the MVP uses MinHash + shingle Jaccard, exposing the same
    ``similarity`` and ``is_contaminated`` interface."""

    def __init__(self, num_perm: int = 32):
        self.num_perm = num_perm
        self._docs: list[dict] = []  # {id, text, sig, shingles}

    def add(self, doc_id: str, text: str):
        self._docs.append({
            "id": doc_id, "text": text,
            "sig": minhash_signature(text, self.num_perm),
            "shingles": char_shingles(text),
        })

    def add_many(self, items: list[tuple[str, str]]):
        for doc_id, text in items:
            self.add(doc_id, text)

    def similarity(self, text: str) -> dict:
        """Return the best match: {score, source_id, method}. score in 0..1."""
        sig = minhash_signature(text, self.num_perm)
        sh = char_shingles(text)
        best = {"score": 0.0, "source_id": None, "method": "minhash"}
        for d in self._docs:
            ms = signature_similarity(sig, d["sig"])
            js = jaccard(sh, d["shingles"])
            ng = ngram_overlap(text, d["text"], n=8)
            score = max(ms, js, ng)
            if score > best["score"]:
                method = "ngram" if ng >= max(ms, js) else ("jaccard" if js >= ms else "minhash")
                best = {"score": round(score, 4), "source_id": d["id"], "method": method}
        return best

    def is_contaminated(self, text: str, threshold: float = 0.6) -> bool:
        return self.similarity(text)["score"] >= threshold


# --------------------------------------------------------------------------- #
# Run-time signals (consumed by authority.verify_and_score-style flows)
# --------------------------------------------------------------------------- #

def canary_echo_count(responses: list[dict], answer_keys: dict) -> int:
    """How many responses echoed their task's canary token (context-dump / leakage)."""
    hits = 0
    by_id = {r["id"]: r for r in responses}
    for tid, key in answer_keys.items():
        c = key.get("canary")
        out = (by_id.get(tid, {}) or {}).get("output", "")
        if c and c in (out or ""):
            hits += 1
    return hits


def suspicious_perfect(score_fraction: float, threshold: float = 0.97) -> bool:
    return score_fraction >= threshold


def timing_anomaly_fraction(responses: list[dict], min_ms: float = 40.0) -> float:
    if not responses:
        return 0.0
    fast = sum(1 for r in responses if float(r.get("latency_ms", 9e9)) < min_ms)
    return fast / len(responses)
