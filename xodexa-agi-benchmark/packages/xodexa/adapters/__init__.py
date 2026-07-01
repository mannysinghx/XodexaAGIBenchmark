"""
xodexa.adapters
=================
The external-eval adapter layer. Other people run other harnesses — lm-eval-harness,
Inspect AI, or just a paper reporting an aggregate accuracy. This package lets those
results flow INTO Xodexa without ever pretending to be an official Xodexa Score.

Why this must exist, and why everything here is NON-OFFICIAL:

The official Xodexa Score is only meaningful when Xodexa controlled inference (hidden
keys, canaries, contamination controls, rotation). The moment an external harness ran
the pack, Xodexa no longer controlled the loop — so any number we derive is, by
construction, *comparison-mode* evidence, not a leaderboard entry. Every result minted
here is stamped ``{"official": False, "mode": "comparison"}``; that stamp is the
invariant the leaderboard filters on, and the tests assert it on every path.

Two clearly-separated ingest modes (see :mod:`xodexa.adapters.core`):

  * **MODE A — raw-output central re-score** (the strong path). The external harness
    captured raw model outputs for a Xodexa pack. We reshape those into the
    ``responses`` list and run the REAL central grader (``evaluate.score_pack``). This
    is legitimately comparison-mode because Xodexa didn't control inference, but the
    *scoring* is central and honest. See :func:`core.central_rescore` fed by the
    per-harness parsers :func:`lm_eval.parse_lm_eval_raw` and
    :func:`inspect_ai.parse_inspect_log`.

  * **MODE B — native-metric anchor** (the weak path). Only an aggregate external
    number exists (e.g. "72.0 on MMLU-Pro"). We normalize it onto the 0..1 capability
    scale via :func:`xodexa.anchors.normalize_score` and label its contamination risk.
    See :func:`core.anchor_result`.
"""

from __future__ import annotations

from .core import (
    central_rescore,
    anchor_result,
    ingest_file,
    COMPARISON_STAMP,
)
from .lm_eval import parse_lm_eval_raw
from .inspect_ai import parse_inspect_log

__all__ = [
    "central_rescore",
    "anchor_result",
    "ingest_file",
    "COMPARISON_STAMP",
    "parse_lm_eval_raw",
    "parse_inspect_log",
]
