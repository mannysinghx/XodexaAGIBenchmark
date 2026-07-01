"""
xodexa.rag
============
A tiny, deterministic BM25 retrieval engine (pure stdlib) so RAG tasks are built on
REAL retrieval instead of a hardcoded "retrieved" block. What lands in the model's
context is decided by BM25 ranking over a seeded corpus — including whether the
poisoned document outranks the honest ones — exactly the dynamics a deployed RAG
system exhibits.

Standard Okapi BM25 (k1=1.5, b=0.75); tokenizer is lowercase alphanumeric split.
Deterministic: same corpus + query -> same ranking (ties broken by doc index).
"""

from __future__ import annotations

import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


class BM25Index:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.docs = list(docs)
        self.k1, self.b = k1, b
        self._toks = [tokenize(d) for d in self.docs]
        self._dl = [len(t) for t in self._toks]
        self._avgdl = (sum(self._dl) / len(self._dl)) if self._dl else 0.0
        self._df: dict[str, int] = {}
        for toks in self._toks:
            for term in set(toks):
                self._df[term] = self._df.get(term, 0) + 1
        self._n = len(self.docs)

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_idx: int) -> float:
        toks = self._toks[doc_idx]
        if not toks:
            return 0.0
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        dl_norm = 1 - self.b + self.b * self._dl[doc_idx] / (self._avgdl or 1.0)
        s = 0.0
        for term in tokenize(query):
            f = tf.get(term, 0)
            if f:
                s += self._idf(term) * f * (self.k1 + 1) / (f + self.k1 * dl_norm)
        return s

    def search(self, query: str, k: int = 4) -> list[tuple[int, float]]:
        """Top-k (doc_index, score), score-desc, doc-index tiebreak (deterministic)."""
        scored = [(i, self.score(query, i)) for i in range(self._n)]
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:k]
