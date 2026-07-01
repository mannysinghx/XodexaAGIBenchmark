"""
xodexa.irt
============
Empirical difficulty from real response data, replacing the hand-assigned floats the
audit flagged ("Difficulty: 9.8 has no definition"). Two complementary estimators:

  * Classical Test Theory (fast, always available): per-item empirical pass-rate ->
    difficulty; item-total point-biserial correlation -> discrimination. Needs only a
    per-(model,item) correctness matrix.
  * 2-parameter logistic IRT (Rasch-style, fitted by alternating MLE / gradient
    ascent, pure Python): estimates item difficulty b and discrimination a on a
    logit scale plus per-model ability theta. Converges on modest data; falls back
    to CTT when a column/row is degenerate (all-right or all-wrong).

Both are deterministic (fixed init, fixed iteration count). Output difficulty is
mapped back to the platform's 0-10 scale so it drops straight into Task.difficulty
and the pipeline's calibration stage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# --------------------------------------------------------------------------- #
# Classical Test Theory
# --------------------------------------------------------------------------- #

def ctt_statistics(matrix: dict[str, dict[str, int]]) -> dict[str, dict]:
    """matrix[model][item] = 0/1 correctness. Returns per-item {pass_rate,
    difficulty_0_10, discrimination, n}. discrimination is the point-biserial
    correlation of item score with each model's total score."""
    models = list(matrix)
    items: set[str] = set()
    for row in matrix.values():
        items.update(row)
    totals = {m: sum(matrix[m].get(it, 0) for it in items) for m in models}

    out: dict[str, dict] = {}
    for it in sorted(items):
        scores = [(m, matrix[m][it]) for m in models if it in matrix[m]]
        n = len(scores)
        if n == 0:
            continue
        p = sum(s for _, s in scores) / n
        # point-biserial: corr(item score, total-minus-item)
        rest = {m: totals[m] - matrix[m].get(it, 0) for m, _ in scores}
        disc = _point_biserial([s for _, s in scores], [rest[m] for m, _ in scores])
        out[it] = {
            "pass_rate": round(p, 4),
            # Harder item (low pass-rate) -> higher difficulty. 0-10 scale.
            "difficulty_0_10": round((1.0 - p) * 10.0, 2),
            "discrimination": round(disc, 4),
            "n": n,
        }
    return out


def _point_biserial(item_scores: list[int], rest_totals: list[float]) -> float:
    n = len(item_scores)
    if n < 2:
        return 0.0
    correct = [r for s, r in zip(item_scores, rest_totals) if s == 1]
    wrong = [r for s, r in zip(item_scores, rest_totals) if s == 0]
    if not correct or not wrong:
        return 0.0
    mean_all = sum(rest_totals) / n
    var = sum((r - mean_all) ** 2 for r in rest_totals) / n
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    p = len(correct) / n
    mc, mw = sum(correct) / len(correct), sum(wrong) / len(wrong)
    return (mc - mw) / sd * math.sqrt(p * (1 - p))


# --------------------------------------------------------------------------- #
# 2PL IRT (Rasch-extended), fitted by alternating gradient ascent
# --------------------------------------------------------------------------- #

@dataclass
class IRTFit:
    difficulty: dict[str, float]         # item -> b (logit scale)
    discrimination: dict[str, float]     # item -> a
    ability: dict[str, float]            # model -> theta
    difficulty_0_10: dict[str, float] = field(default_factory=dict)
    iterations: int = 0
    degenerate_items: list[str] = field(default_factory=list)


def fit_2pl(matrix: dict[str, dict[str, int]], iters: int = 300,
            lr: float = 0.05) -> IRTFit:
    """Fit a 2PL model. Deterministic (zero init, fixed schedule). Degenerate items
    (all models right or all wrong) can't be fit on a logit scale — they are pinned
    to an extreme b and reported in degenerate_items."""
    models = list(matrix)
    items: list[str] = sorted({it for row in matrix.values() for it in row})
    theta = {m: 0.0 for m in models}
    a = {it: 1.0 for it in items}
    b = {it: 0.0 for it in items}

    degenerate = []
    for it in items:
        col = [matrix[m][it] for m in models if it in matrix[m]]
        if col and (all(col) or not any(col)):
            degenerate.append(it)
            b[it] = -4.0 if all(col) else 4.0  # trivial vs impossible
            a[it] = 0.3

    active = [it for it in items if it not in degenerate]
    for step in range(iters):
        # ability gradient
        for m in models:
            g = 0.0
            for it in matrix[m]:
                if it in degenerate:
                    continue
                x = matrix[m][it]
                p = _sigmoid(a[it] * (theta[m] - b[it]))
                g += a[it] * (x - p)
            theta[m] += lr * g
        # item gradients
        for it in active:
            ga = gb = 0.0
            for m in models:
                if it not in matrix[m]:
                    continue
                x = matrix[m][it]
                p = _sigmoid(a[it] * (theta[m] - b[it]))
                err = x - p
                ga += err * (theta[m] - b[it])
                gb += -a[it] * err
            a[it] = max(0.1, a[it] + lr * ga)
            b[it] += lr * gb

    # Map b (roughly [-4, 4]) onto 0-10 difficulty.
    diff_0_10 = {it: round(max(0.0, min(10.0, (b[it] + 4.0) / 8.0 * 10.0)), 2)
                 for it in items}
    return IRTFit(difficulty={k: round(v, 4) for k, v in b.items()},
                  discrimination={k: round(v, 4) for k, v in a.items()},
                  ability={k: round(v, 4) for k, v in theta.items()},
                  difficulty_0_10=diff_0_10, iterations=iters,
                  degenerate_items=degenerate)


# --------------------------------------------------------------------------- #
# Item-quality gate
# --------------------------------------------------------------------------- #

def flag_bad_items(stats: dict[str, dict], min_discrimination: float = 0.1,
                   max_pass_rate: float = 0.98, min_pass_rate: float = 0.0) -> dict:
    """Given CTT stats, split items into keep / drop. Non-discriminating items
    (everyone gets them same) and trivially-easy items carry no signal and should be
    rotated out — the pipeline's difficulty_filter has the hook; this supplies the
    empirical basis instead of a probe heuristic."""
    keep, drop = [], []
    for it, s in stats.items():
        reason = None
        if s["pass_rate"] > max_pass_rate:
            reason = f"too easy (pass_rate {s['pass_rate']})"
        elif s["pass_rate"] < min_pass_rate:
            reason = f"impossible (pass_rate {s['pass_rate']})"
        elif abs(s["discrimination"]) < min_discrimination:
            reason = f"non-discriminating (r={s['discrimination']})"
        (drop if reason else keep).append(
            {"item": it, "reason": reason} if reason else it)
    return {"keep": keep, "drop": drop}
