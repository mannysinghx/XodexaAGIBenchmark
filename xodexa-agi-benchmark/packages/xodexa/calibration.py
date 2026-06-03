"""
xodexa.calibration
=====================
Frontier-grade honesty metrics, adopted and extended from Humanity's Last Exam
(Scale AI / CAIS) and the Open LLM Leaderboard:

  * accuracy(...)              — fraction correct (HLE's headline number).
  * wilson_ci(...)             — 95% confidence interval on a proportion.
  * rms_calibration_error(...) — RMS calibration error (Hendrycks et al. 2022 style):
                                 a model is well-calibrated when stated confidence
                                 matches realized accuracy. HLE reports CE>80% for most
                                 frontier models → systematic overconfidence/confabulation.
  * rank_upper_bound(...)      — HLE's ranking rule: rank = 1 + (# models statistically
                                 significantly better), where "better" means a model's
                                 lower CI bound exceeds this model's upper CI bound.
                                 This groups models by significance, not raw score.

All percentages are on a 0-100 scale to match how leaderboards display them.
"""

from __future__ import annotations

import math


def accuracy(correct: int, total: int) -> float:
    return 100.0 * correct / total if total else 0.0


def wilson_ci(correct: int, total: int, z: float = 1.96) -> tuple[float, float, float]:
    """
    Wilson score interval for a binomial proportion (better than normal approx at the
    extremes where HLE lives — accuracies near 0). Returns (point, half_width, ci_pct).
    `half_width` is the symmetric-ish ± shown on leaderboards (avg of the two arms).
    """
    if total == 0:
        return (0.0, 0.0, 0.0)
    p = correct / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = (z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))) / denom
    lo = max(0.0, center - margin) * 100
    hi = min(1.0, center + margin) * 100
    point = p * 100
    half = (hi - lo) / 2
    return (round(point, 2), round(half, 2), round(point, 2))


def rms_calibration_error(confidences: list[float], correct: list[int],
                          n_bins: int = 15) -> float:
    """
    RMS calibration error on a 0-100 scale.

        RMS-CE = sqrt( Σ_b (n_b / N) * (acc_b - conf_b)^2 )

    confidences: model-stated confidence per item, each in [0,1] (or [0,100]).
    correct:     1/0 correctness per item, aligned with confidences.
    Bins are fixed-width over [0,1]. Empty bins are skipped.
    """
    if not confidences or len(confidences) != len(correct):
        return 0.0
    conf = [c / 100.0 if c > 1.0 else c for c in confidences]
    N = len(conf)
    bins = [[] for _ in range(n_bins)]
    for c, y in zip(conf, correct):
        idx = min(n_bins - 1, int(c * n_bins))
        bins[idx].append((c, y))
    total = 0.0
    for b in bins:
        if not b:
            continue
        nb = len(b)
        acc_b = sum(y for _, y in b) / nb
        conf_b = sum(c for c, _ in b) / nb
        total += (nb / N) * (acc_b - conf_b) ** 2
    return round(100.0 * math.sqrt(total), 1)


def rank_upper_bound(entries: list[dict]) -> list[dict]:
    """
    Assign HLE-style Rank (Upper Bound). Each entry needs `score` and `ci` (half-width).
    A model j is 'significantly better' than i iff (score_j - ci_j) > (score_i + ci_i).
    rank_i = 1 + |{ j : j significantly better than i }|.
    Returns entries (sorted by score desc) each annotated with `rank_ub`, `ci_low`,
    `ci_high`. Ties (same count of betters) share a rank, exactly like HLE.
    """
    ann = []
    for e in entries:
        lo = e["score"] - e.get("ci", 0.0)
        hi = e["score"] + e.get("ci", 0.0)
        ann.append({**e, "ci_low": round(lo, 2), "ci_high": round(hi, 2)})
    for i in ann:
        better = sum(1 for j in ann if j is not i and j["ci_low"] > i["ci_high"])
        i["rank_ub"] = better + 1
    ann.sort(key=lambda e: e["score"], reverse=True)
    return ann
