"""
xodexa.stats
==============
Statistical machinery that turns leaderboard differences from *suggestive* into
*defensible*:

  * McNemar exact test — the correct paired test for two models graded on the SAME
    fixed-seed task pack (see ScoringAuthority.issue_manifest(fixed_seed=...)).
  * Paired bootstrap — CI + p-value on the mean per-item score difference.
  * Benjamini-Hochberg FDR — a leaderboard of M models implies M(M-1)/2 pairwise
    comparisons; without FDR control, "significant" gaps appear by chance alone.
  * Cohen's d (paired) — effect size, because p < 0.05 on a 2-point gap is not news.
  * pass@k — the unbiased Chen et al. (HumanEval) estimator for repeated sampling.
  * min-n gate — runs below MIN_ITEMS_FOR_RANKING are labeled insufficient for
    head-to-head ranking (wide Wilson CIs make their ranks meaningless).

Pure stdlib (math/random), deterministic where seeded — same contract as the rest
of the engine.
"""

from __future__ import annotations

import math
import random

# Below this many graded items, CIs are so wide that a rank is noise. Runs under the
# gate still get a score — they are just excluded from significance-ranked ordering.
MIN_ITEMS_FOR_RANKING = 30


# --------------------------------------------------------------------------- #
# Paired tests (require both models on the SAME task set — fixed-seed packs)
# --------------------------------------------------------------------------- #

def mcnemar_exact(a_correct: list[int], b_correct: list[int]) -> dict:
    """Exact (binomial) McNemar test on paired binary outcomes.

    ``a_correct[i]`` / ``b_correct[i]`` are 0/1 correctness of models A and B on the
    same task i. Only discordant pairs carry information: b = A right & B wrong,
    c = A wrong & B right. Under H0 (no difference) discordants split 50/50; the
    two-sided exact p-value is the binomial tail doubled.
    """
    if len(a_correct) != len(b_correct):
        raise ValueError("paired test needs equal-length outcome vectors")
    b = sum(1 for x, y in zip(a_correct, b_correct) if x and not y)
    c = sum(1 for x, y in zip(a_correct, b_correct) if not x and y)
    n = b + c
    if n == 0:
        return {"b": 0, "c": 0, "n_discordant": 0, "p_value": 1.0}
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * 0.5 ** n
    p = min(1.0, 2.0 * tail)
    return {"b": b, "c": c, "n_discordant": n, "p_value": round(p, 6)}


def paired_bootstrap(scores_a: list[float], scores_b: list[float],
                     iters: int = 10000, seed: int = 0) -> dict:
    """Bootstrap the mean per-item difference (A - B) over paired scores.

    Returns mean_diff, a 95% percentile CI, and a two-sided bootstrap p-value
    (fraction of resampled means on the far side of zero, doubled). Deterministic
    for a given seed — same reproducibility contract as the scoring bootstrap.
    """
    if len(scores_a) != len(scores_b):
        raise ValueError("paired test needs equal-length score vectors")
    diffs = [a - b for a, b in zip(scores_a, scores_b)]
    if not diffs:
        return {"mean_diff": 0.0, "ci95": (0.0, 0.0), "p_value": 1.0}
    rng = random.Random(seed)
    n = len(diffs)
    means = []
    for _ in range(iters):
        s = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(s) / n)
    means.sort()
    lo, hi = means[int(0.025 * iters)], means[int(0.975 * iters)]
    mean_diff = sum(diffs) / n
    # two-sided: how often the resampled mean crosses zero against the observed sign
    if mean_diff >= 0:
        crossings = sum(1 for m in means if m <= 0)
    else:
        crossings = sum(1 for m in means if m >= 0)
    p = min(1.0, 2.0 * crossings / iters)
    return {"mean_diff": round(mean_diff, 6), "ci95": (round(lo, 6), round(hi, 6)),
            "p_value": round(p, 6)}


def cohens_d_paired(scores_a: list[float], scores_b: list[float]) -> float:
    """Paired Cohen's d: mean(diff) / std(diff). 0.2 small / 0.5 medium / 0.8 large."""
    diffs = [a - b for a, b in zip(scores_a, scores_b)]
    n = len(diffs)
    if n < 2:
        return 0.0
    mean = sum(diffs) / n
    var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
    sd = math.sqrt(var)
    return round(mean / sd, 6) if sd > 0 else 0.0


# --------------------------------------------------------------------------- #
# Multiple-comparisons control
# --------------------------------------------------------------------------- #

def benjamini_hochberg(p_values: list[float], alpha: float = 0.05) -> dict:
    """Benjamini-Hochberg FDR control.

    Returns {"reject": [bool per input p], "adjusted": [BH-adjusted p per input]}.
    reject[i] is True when p_values[i] survives FDR control at ``alpha``.
    """
    m = len(p_values)
    if m == 0:
        return {"reject": [], "adjusted": []}
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    prev = 1.0
    # step-up: adjusted p is monotone non-decreasing from the largest p downwards
    for rank_from_end in range(m, 0, -1):
        i = order[rank_from_end - 1]
        adj = min(prev, p_values[i] * m / rank_from_end)
        adjusted[i] = round(adj, 6)
        prev = adj
    reject = [adjusted[i] <= alpha for i in range(m)]
    return {"reject": reject, "adjusted": adjusted}


def pairwise_significance(models: dict[str, list[int]], alpha: float = 0.05) -> list[dict]:
    """All-pairs McNemar over models graded on the SAME fixed-seed pack, with BH-FDR.

    ``models`` maps model name -> per-task 0/1 correctness, aligned by task index.
    Returns one record per pair with raw p, BH-adjusted p, and the FDR verdict.
    """
    names = sorted(models)
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]]
    results = [dict({"model_a": a, "model_b": b}, **mcnemar_exact(models[a], models[b]))
               for a, b in pairs]
    bh = benjamini_hochberg([r["p_value"] for r in results], alpha)
    for r, adj, rej in zip(results, bh["adjusted"], bh["reject"]):
        r["p_adjusted"] = adj
        r["significant"] = rej
    return results


# --------------------------------------------------------------------------- #
# Repeated sampling
# --------------------------------------------------------------------------- #

def pass_at_k(n: int, c: int, k: int) -> float:
    """Unbiased pass@k estimator (Chen et al., 2021): probability that at least one
    of k draws from n samples (of which c are correct) is correct.

    pass@k = 1 - C(n-c, k) / C(n, k)
    """
    if k <= 0 or n <= 0:
        raise ValueError("n and k must be positive")
    if k > n:
        raise ValueError("k cannot exceed the number of samples n")
    if c <= 0:
        return 0.0
    if n - c < k:
        return 1.0
    return round(1.0 - math.comb(n - c, k) / math.comb(n, k), 6)


def aggregate_pass_at_k(per_task_samples: dict[str, list[int]],
                        ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    """Mean pass@k over tasks. ``per_task_samples`` maps task_id -> list of 0/1
    correctness across n sampled attempts. Ks larger than a task's sample count are
    skipped for that task (and the effective task count reported)."""
    out: dict = {}
    for k in ks:
        vals = [pass_at_k(len(s), sum(s), k)
                for s in per_task_samples.values() if len(s) >= k]
        if vals:
            out[f"pass@{k}"] = round(sum(vals) / len(vals), 6)
            out[f"pass@{k}_tasks"] = len(vals)
    return out


# --------------------------------------------------------------------------- #
# Sample-size gate
# --------------------------------------------------------------------------- #

def min_n_gate(n_items: int, min_n: int = MIN_ITEMS_FOR_RANKING) -> dict:
    """Whether a run has enough graded items to participate in significance-ranked
    ordering. Insufficient runs keep their score but carry this flag."""
    return {"n_items": n_items, "min_n": min_n, "sufficient": n_items >= min_n}
