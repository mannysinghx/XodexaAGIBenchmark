"""Phase-3 tests: empirical IRT difficulty, contamination paraphrase catch-rate,
and the frontier-sweep pipeline end-to-end (offline sim fleet)."""

import subprocess
import sys
from pathlib import Path

import pytest

from xodexa.contamination import CorpusIndex
from xodexa.irt import ctt_statistics, fit_2pl, flag_bad_items

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# IRT / CTT
# --------------------------------------------------------------------------- #

def _matrix():
    # 4 models of increasing ability × 5 items of increasing difficulty.
    # item0 easy (all pass) ... item4 hard (only best passes).
    return {
        "weak":   {"i0": 1, "i1": 0, "i2": 0, "i3": 0, "i4": 0},
        "mid":    {"i0": 1, "i1": 1, "i2": 0, "i3": 0, "i4": 0},
        "strong": {"i0": 1, "i1": 1, "i2": 1, "i3": 1, "i4": 0},
        "top":    {"i0": 1, "i1": 1, "i2": 1, "i3": 1, "i4": 1},
    }


def test_ctt_difficulty_orders_items():
    s = ctt_statistics(_matrix())
    # i0 easiest (pass_rate 1.0 -> difficulty 0), i4 hardest (pass_rate 0.25).
    assert s["i0"]["difficulty_0_10"] < s["i2"]["difficulty_0_10"] < s["i4"]["difficulty_0_10"]
    assert s["i0"]["pass_rate"] == 1.0


def test_ctt_discrimination_positive_for_good_item():
    s = ctt_statistics(_matrix())
    # i1..i3 separate abilities -> positive point-biserial.
    assert s["i2"]["discrimination"] > 0


def test_irt_ability_orders_models():
    fit = fit_2pl(_matrix(), iters=200)
    assert fit.ability["top"] > fit.ability["strong"] > fit.ability["weak"]


def test_irt_flags_degenerate_all_pass_item():
    m = _matrix()
    fit = fit_2pl(m, iters=100)
    assert "i0" in fit.degenerate_items  # everyone passes -> can't fit on logit scale


def test_flag_bad_items_drops_non_discriminating():
    # An item everyone gets right carries no signal.
    m = {"a": {"x": 1, "y": 1}, "b": {"x": 1, "y": 0}, "c": {"x": 1, "y": 1}}
    q = flag_bad_items(ctt_statistics(m))
    dropped = {d["item"] for d in q["drop"]}
    assert "x" in dropped  # pass_rate 1.0 -> too easy / non-discriminating


# --------------------------------------------------------------------------- #
# Contamination paraphrase catch-rate (the audit gap)
# --------------------------------------------------------------------------- #

def test_verbatim_contamination_caught():
    idx = CorpusIndex()
    idx.add("mmlu-1", "What is the capital of the country whose currency is the yen?")
    hit = idx.similarity("What is the capital of the country whose currency is the yen?")
    assert hit["score"] > 0.9


def test_reordered_paraphrase_caught_by_token_containment():
    idx = CorpusIndex()
    idx.add("src", "the mitochondria is the powerhouse of the cell and produces atp")
    # Same bag of words, reordered — surface n-gram/shingle overlap is low, but
    # token containment catches it.
    probe = "atp is produced by the cell powerhouse which is the mitochondria of the"
    hit = idx.similarity(probe)
    assert hit["score"] >= 0.6
    assert hit["method"] == "token_containment"


def test_unrelated_text_not_flagged():
    idx = CorpusIndex()
    idx.add("src", "the mitochondria is the powerhouse of the cell")
    hit = idx.similarity("a recipe for sourdough bread using a wild yeast starter")
    assert hit["score"] < 0.3


def test_short_probe_embedded_in_long_source_flagged():
    idx = CorpusIndex()
    idx.add("src", "In this long passage about thermodynamics we eventually note that "
                   "entropy of an isolated system never decreases over time, plus much "
                   "more surrounding context that pads the document considerably.")
    hit = idx.similarity("entropy of an isolated system never decreases over time")
    assert hit["score"] >= 0.6


# --------------------------------------------------------------------------- #
# Hidden-set rotation script (dry run)
# --------------------------------------------------------------------------- #

def test_rotate_hidden_set_dry_run():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "rotate_hidden_set.py"),
         "--dry-run", "--scale", "0.05"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    assert "dry-run" in r.stdout and "no files written" in r.stdout


# --------------------------------------------------------------------------- #
# Frontier sweep (offline sim fleet)
# --------------------------------------------------------------------------- #

def test_frontier_sweep_offline(tmp_path):
    out = tmp_path / "sweep.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "frontier_sweep.py"),
         "--family", "reasoning", "--n", "20", "--seed", "3",
         "--out", str(out.relative_to(ROOT)) if out.is_relative_to(ROOT) else "results/_t.json"],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr
    # Higher-skill sim persona must top the leaderboard.
    import json
    written = out if out.exists() else (ROOT / "results" / "_t.json")
    data = json.loads(written.read_text())
    lb = data["leaderboard"]
    assert lb[0]["accuracy"] >= lb[-1]["accuracy"]
    assert data["n_items"] == 20
    assert "item_difficulty" in data and len(data["item_difficulty"]) > 0
    written.unlink(missing_ok=True)
