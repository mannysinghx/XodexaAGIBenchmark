"""Unit tests for xodexa.stability (re-run reproducibility metric)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages"))

from xodexa.stability import rerun_stability, stability_index


def test_needs_two_runs():
    out = rerun_stability([700.0])
    assert out["sufficient"] is False
    assert out["runs"] == 1


def test_identical_runs_are_perfectly_stable():
    out = rerun_stability([720.0, 720.0, 720.0])
    assert out["score"]["std"] == 0.0
    assert out["stability_index"] == 1.0
    assert out["sufficient"] is True


def test_volatile_runs_score_low_stability():
    stable = rerun_stability([700.0, 705.0, 698.0])["stability_index"]
    volatile = rerun_stability([600.0, 800.0, 700.0])["stability_index"]
    assert stable > volatile
    assert volatile < 0.3                       # ~81-point std -> low stability
    # a 100-point std (two runs a grade-band apart) collapses the index to 0
    assert rerun_stability([600.0, 800.0])["stability_index"] == 0.0


def test_stability_index_monotonic_and_bounded():
    assert stability_index(0.0) == 1.0
    assert stability_index(50.0) == 0.5
    assert stability_index(100.0) == 0.0
    assert stability_index(250.0) == 0.0  # clamped, never negative


def test_family_volatility_flags_least_stable():
    scores = [700.0, 720.0]
    fam = [
        {"reasoning": 0.80, "safety": 0.90},   # run 1
        {"reasoning": 0.82, "safety": 0.50},   # run 2 — safety swung hard
    ]
    out = rerun_stability(scores, family_scores=fam)
    assert out["least_stable_family"] == "safety"
    assert out["family_volatility"][0]["family"] == "safety"
