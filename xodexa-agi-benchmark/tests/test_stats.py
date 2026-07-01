"""Tests for xodexa.stats — paired tests, FDR control, pass@k, min-n gating —
plus the fixed-seed comparison-pack and insufficient-n integrations."""

import math

import pytest

from xodexa.stats import (
    MIN_ITEMS_FOR_RANKING,
    aggregate_pass_at_k,
    benjamini_hochberg,
    cohens_d_paired,
    mcnemar_exact,
    min_n_gate,
    paired_bootstrap,
    pairwise_significance,
    pass_at_k,
)
from xodexa.scoring import apex_score


# --------------------------------------------------------------------------- #
# McNemar exact
# --------------------------------------------------------------------------- #

def test_mcnemar_identical_models_p_is_one():
    a = [1, 0, 1, 1, 0] * 10
    r = mcnemar_exact(a, list(a))
    assert r["n_discordant"] == 0 and r["p_value"] == 1.0


def test_mcnemar_one_sided_dominance_significant():
    # A right where B wrong on 15 items, never the reverse -> p = 2 * 0.5^15
    a = [1] * 15 + [1] * 10
    b = [0] * 15 + [1] * 10
    r = mcnemar_exact(a, b)
    assert r["b"] == 15 and r["c"] == 0
    assert r["p_value"] == pytest.approx(2 * 0.5 ** 15, rel=1e-3)


def test_mcnemar_balanced_discordants_not_significant():
    a = [1, 0] * 10
    b = [0, 1] * 10
    r = mcnemar_exact(a, b)
    assert r["b"] == r["c"] == 10
    assert r["p_value"] > 0.5


def test_mcnemar_length_mismatch_raises():
    with pytest.raises(ValueError):
        mcnemar_exact([1, 0], [1])


# --------------------------------------------------------------------------- #
# Paired bootstrap + effect size
# --------------------------------------------------------------------------- #

def test_paired_bootstrap_detects_consistent_gap():
    a = [0.8 + 0.01 * (i % 3) for i in range(50)]
    b = [0.6 + 0.01 * (i % 3) for i in range(50)]
    r = paired_bootstrap(a, b, iters=2000, seed=1)
    assert r["mean_diff"] == pytest.approx(0.2, abs=1e-9)
    assert r["ci95"][0] > 0.19 and r["p_value"] < 0.01


def test_paired_bootstrap_null_gap_not_significant():
    a = [1.0, 0.0] * 25
    b = [0.0, 1.0] * 25
    r = paired_bootstrap(a, b, iters=2000, seed=1)
    assert r["p_value"] > 0.5
    assert r["ci95"][0] < 0 < r["ci95"][1]


def test_paired_bootstrap_deterministic():
    a, b = [1.0, 0.5, 0.0] * 10, [0.5, 0.5, 0.5] * 10
    assert paired_bootstrap(a, b, seed=7) == paired_bootstrap(a, b, seed=7)


def test_cohens_d_large_effect():
    a = [1.0] * 20
    b = [0.0] * 19 + [1.0]  # nearly-constant unit differences
    assert cohens_d_paired(a, b) > 0.8


# --------------------------------------------------------------------------- #
# Benjamini-Hochberg
# --------------------------------------------------------------------------- #

def test_bh_rejects_only_survivors():
    ps = [0.001, 0.008, 0.039, 0.041, 0.9]
    r = benjamini_hochberg(ps, alpha=0.05)
    assert r["reject"][0] and r["reject"][1]
    assert not r["reject"][4]
    # adjusted p-values are monotone in the sorted order and >= raw p
    assert all(adj >= p for adj, p in zip(r["adjusted"], ps))


def test_bh_empty_input():
    assert benjamini_hochberg([]) == {"reject": [], "adjusted": []}


def test_pairwise_significance_matrix():
    strong = [1] * 40 + [1] * 10
    weak = [0] * 40 + [1] * 10
    mid = [1] * 20 + [0] * 20 + [1] * 10
    res = pairwise_significance({"strong": strong, "weak": weak, "mid": mid})
    assert len(res) == 3  # 3 choose 2
    sw = next(r for r in res if {r["model_a"], r["model_b"]} == {"strong", "weak"})
    assert sw["significant"]
    assert all("p_adjusted" in r for r in res)


# --------------------------------------------------------------------------- #
# pass@k
# --------------------------------------------------------------------------- #

def test_pass_at_k_all_correct():
    assert pass_at_k(5, 5, 1) == 1.0


def test_pass_at_k_none_correct():
    assert pass_at_k(5, 0, 3) == 0.0


def test_pass_at_1_equals_fraction_correct():
    assert pass_at_k(10, 3, 1) == pytest.approx(0.3)


def test_pass_at_k_unbiased_formula():
    # n=5, c=2, k=3 -> 1 - C(3,3)/C(5,3) = 1 - 1/10
    assert pass_at_k(5, 2, 3) == pytest.approx(0.9)


def test_pass_at_k_k_exceeds_n_raises():
    with pytest.raises(ValueError):
        pass_at_k(3, 1, 5)


def test_aggregate_pass_at_k_skips_short_samples():
    r = aggregate_pass_at_k({"t1": [1, 0, 1, 0, 0], "t2": [0, 1]}, ks=(1, 5))
    assert r["pass@1_tasks"] == 2
    assert r["pass@5_tasks"] == 1  # t2 has only 2 samples


# --------------------------------------------------------------------------- #
# min-n gate + apex integration
# --------------------------------------------------------------------------- #

def test_min_n_gate():
    assert not min_n_gate(10)["sufficient"]
    assert min_n_gate(MIN_ITEMS_FOR_RANKING)["sufficient"]


def test_apex_score_flags_insufficient_n():
    few = [{"category": "reasoning", "awarded": 1.0, "max": 1.0} for _ in range(5)]
    r = apex_score(few)
    assert r["insufficient_n"] and r["n_items"] == 5
    many = few * 8  # 40 items
    r2 = apex_score(many)
    assert not r2["insufficient_n"] and r2["n_items"] == 40


# --------------------------------------------------------------------------- #
# Fixed-seed comparison packs (paired-test prerequisite)
# --------------------------------------------------------------------------- #

def test_fixed_seed_comparison_packs_serve_identical_tasks():
    from xodexa.authority import ScoringAuthority
    from xodexa.runner import RunnerAgent

    auth = ScoringAuthority()
    runner = RunnerAgent()
    runner.register(auth)
    a = auth.issue_manifest(runner.runner_id, "xodexa-omega", fixed_seed=42)
    b = auth.issue_manifest(runner.runner_id, "xodexa-omega", fixed_seed=42)
    assert a["manifest"]["seed_mode"] == "fixed"
    assert a["manifest"]["run_seed"] == b["manifest"]["run_seed"] == 42
    # identical items -> paired tests are valid across the two runs
    assert [t["id"] for t in a["public_tasks"]] == [t["id"] for t in b["public_tasks"]]
    assert [t["prompt"] for t in a["public_tasks"]] == [t["prompt"] for t in b["public_tasks"]]
    # replay protection untouched: fresh nonce + run_id per issuance
    assert a["manifest"]["nonce"] != b["manifest"]["nonce"]
    assert a["manifest"]["run_id"] != b["manifest"]["run_id"]


def test_default_manifest_still_nonce_seeded():
    from xodexa.authority import ScoringAuthority
    from xodexa.runner import RunnerAgent

    auth = ScoringAuthority()
    runner = RunnerAgent()
    runner.register(auth)
    m = auth.issue_manifest(runner.runner_id, "xodexa-omega")
    assert m["manifest"]["seed_mode"] == "nonce"
