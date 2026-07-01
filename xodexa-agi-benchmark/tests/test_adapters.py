"""
Tests for the external-eval adapter layer (xodexa.adapters).

The whole point of these tests is to prove two things at once for BOTH ingest modes:
(1) external results genuinely flow in and score correctly — MODE A actually runs the
central grader, MODE B actually normalizes — and (2) NOTHING that comes out can pass
for an official score. Every returned dict is asserted to carry official==False and
mode=="comparison"; that invariant is the guard that keeps these off the leaderboard.

All offline, stdlib + the in-repo generators only. No network.
"""

import json

import pytest

from xodexa import grade, schema
from xodexa.generators import generate_from
from xodexa import adapters
from xodexa.adapters import core


GEN_ID = "code.exec_filter_fold"


def _pack(n=3, seed=1):
    """A tiny real Xodexa pack + its server-side answer_keys dict."""
    tasks = generate_from(GEN_ID, n, seed=seed)
    keys = {t.task_id: schema.answer_key(t) for t in tasks}
    return tasks, keys


def _assert_comparison(d):
    """The invariant that keeps external results off the official leaderboard."""
    assert d["official"] is False
    assert d["mode"] == "comparison"


# --------------------------------------------------------------------------- #
# MODE A — lm-eval raw-output central re-score
# --------------------------------------------------------------------------- #

def test_mode_a_lm_eval_embedded_id_full_marks():
    tasks, keys = _pack()
    # Fake lm-eval records: each embeds xodexa_task_id + a CORRECT output.
    records = [
        {"doc_id": i, "xodexa_task_id": t.task_id,
         "filtered_resps": [grade.synth_good(keys[t.task_id]["grader"])]}
        for i, t in enumerate(tasks)
    ]
    responses = adapters.parse_lm_eval_raw(records)
    assert len(responses) == len(tasks)
    assert all(set(r) >= {"id", "output"} for r in responses)

    result = core.central_rescore(keys, responses, source="lm-eval-harness")
    _assert_comparison(result)
    assert result["source"] == "lm-eval-harness"
    assert result["scoring"] == "central-re-score"
    # Every item full marks -> accuracy 1.0 over all n items, none errored.
    assert result["frontier_metrics"]["accuracy"] == 100.0
    assert result["frontier_metrics"]["n"] == len(tasks)
    assert result["frontier_metrics"]["errored"] == 0
    total_awarded = sum(r["awarded"] for r in result["item_results"])
    total_max = sum(r["max"] for r in result["item_results"])
    assert total_awarded == total_max


def test_mode_a_lm_eval_wrong_output_scores_lower():
    tasks, keys = _pack()
    good = [
        {"xodexa_task_id": t.task_id,
         "resps": [grade.synth_good(keys[t.task_id]["grader"])]}
        for t in tasks
    ]
    bad = [
        {"xodexa_task_id": t.task_id,
         "resps": [grade.synth_bad(keys[t.task_id]["grader"])]}
        for t in tasks
    ]
    good_res = core.central_rescore(keys, adapters.parse_lm_eval_raw(good), "lm-eval")
    bad_res = core.central_rescore(keys, adapters.parse_lm_eval_raw(bad), "lm-eval")
    _assert_comparison(good_res)
    _assert_comparison(bad_res)
    good_awarded = sum(r["awarded"] for r in good_res["item_results"])
    bad_awarded = sum(r["awarded"] for r in bad_res["item_results"])
    assert bad_awarded < good_awarded
    assert bad_res["frontier_metrics"]["accuracy"] < good_res["frontier_metrics"]["accuracy"]


def test_mode_a_lm_eval_id_map_path():
    tasks, keys = _pack()
    # Records keyed by NATIVE lm-eval doc_id only; bridge via an explicit id_map.
    records = [
        {"doc_id": i, "filtered_resps": [grade.synth_good(keys[t.task_id]["grader"])]}
        for i, t in enumerate(tasks)
    ]
    id_map = {str(i): t.task_id for i, t in enumerate(tasks)}
    responses = adapters.parse_lm_eval_raw(records, id_map=id_map)
    assert {r["id"] for r in responses} == set(keys)

    result = core.central_rescore(keys, responses, source="lm-eval")
    _assert_comparison(result)
    assert result["frontier_metrics"]["accuracy"] == 100.0


def test_mode_a_lm_eval_full_results_object_and_unmapped_dropped():
    tasks, keys = _pack()
    # Full results object with samples grouped by task-name; plus one alien record
    # that maps to no Xodexa id and must be dropped.
    samples = {
        "xodexa_task": [
            {"doc_id": i, "xodexa_task_id": t.task_id,
             "filtered_resps": [grade.synth_good(keys[t.task_id]["grader"])]}
            for i, t in enumerate(tasks)
        ] + [{"doc_id": 999, "filtered_resps": ["irrelevant"]}]
    }
    responses = adapters.parse_lm_eval_raw({"samples": samples})
    assert len(responses) == len(tasks)  # alien record dropped
    result = core.central_rescore(keys, responses, "lm-eval")
    _assert_comparison(result)
    assert result["frontier_metrics"]["accuracy"] == 100.0


# --------------------------------------------------------------------------- #
# MODE A — Inspect AI eval-log central re-score
# --------------------------------------------------------------------------- #

def test_mode_a_inspect_completion_full_marks():
    tasks, keys = _pack()
    eval_log = {
        "samples": [
            {"id": t.task_id,
             "output": {"completion": grade.synth_good(keys[t.task_id]["grader"])}}
            for t in tasks
        ]
    }
    responses = adapters.parse_inspect_log(eval_log)
    assert len(responses) == len(tasks)
    result = core.central_rescore(keys, responses, source="inspect-ai")
    _assert_comparison(result)
    assert result["frontier_metrics"]["accuracy"] == 100.0


def test_mode_a_inspect_messages_and_metadata_id():
    tasks, keys = _pack()
    # Output via the message transcript, id via metadata.xodexa_task_id.
    eval_log = {
        "samples": [
            {"id": f"native-{i}",
             "metadata": {"xodexa_task_id": t.task_id},
             "messages": [
                 {"role": "user", "content": "solve it"},
                 {"role": "assistant",
                  "content": [{"type": "text",
                               "text": grade.synth_good(keys[t.task_id]["grader"])}]},
             ]}
            for i, t in enumerate(tasks)
        ]
    }
    responses = adapters.parse_inspect_log(eval_log)
    assert {r["id"] for r in responses} == set(keys)
    result = core.central_rescore(keys, responses, "inspect-ai")
    _assert_comparison(result)
    assert result["frontier_metrics"]["accuracy"] == 100.0


def test_mode_a_inspect_wrong_scores_lower():
    tasks, keys = _pack()
    good_log = {"samples": [
        {"id": t.task_id, "output": {"completion": grade.synth_good(keys[t.task_id]["grader"])}}
        for t in tasks]}
    bad_log = {"samples": [
        {"id": t.task_id, "output": {"completion": grade.synth_bad(keys[t.task_id]["grader"])}}
        for t in tasks]}
    good_res = core.central_rescore(keys, adapters.parse_inspect_log(good_log), "inspect")
    bad_res = core.central_rescore(keys, adapters.parse_inspect_log(bad_log), "inspect")
    _assert_comparison(good_res)
    _assert_comparison(bad_res)
    assert (sum(r["awarded"] for r in bad_res["item_results"])
            < sum(r["awarded"] for r in good_res["item_results"]))


# --------------------------------------------------------------------------- #
# MODE B — native-metric anchor
# --------------------------------------------------------------------------- #

def test_mode_b_anchor_mmlu_pro():
    r = core.anchor_result("mmlu_pro", 72.0, 100, "paper")
    _assert_comparison(r)
    assert r["anchor"] == "mmlu_pro"
    assert r["normalized_0_1"] == pytest.approx(0.72)
    assert r["contamination_risk"] == "high"
    assert r["n_items"] == 100
    assert r["native_value"] == 72.0
    assert r["source"] == "paper"


def test_mode_b_unknown_anchor_raises():
    with pytest.raises(KeyError):
        core.anchor_result("not_a_real_anchor", 50.0, 10, "paper")


# --------------------------------------------------------------------------- #
# ingest_file dispatch
# --------------------------------------------------------------------------- #

def test_ingest_file_lm_eval(tmp_path):
    tasks, keys = _pack()
    records = [
        {"doc_id": i, "xodexa_task_id": t.task_id,
         "filtered_resps": [grade.synth_good(keys[t.task_id]["grader"])]}
        for i, t in enumerate(tasks)
    ]
    p = tmp_path / "lm_eval.json"
    p.write_text(json.dumps(records))
    result = core.ingest_file(str(p), "lm-eval-raw", answer_keys=keys)
    _assert_comparison(result)
    assert result["frontier_metrics"]["accuracy"] == 100.0


def test_ingest_file_inspect(tmp_path):
    tasks, keys = _pack()
    eval_log = {"samples": [
        {"id": t.task_id, "output": {"completion": grade.synth_good(keys[t.task_id]["grader"])}}
        for t in tasks]}
    p = tmp_path / "inspect.json"
    p.write_text(json.dumps(eval_log))
    result = core.ingest_file(str(p), "inspect-log", answer_keys=keys)
    _assert_comparison(result)
    assert result["frontier_metrics"]["accuracy"] == 100.0


def test_ingest_file_anchor_from_file(tmp_path):
    p = tmp_path / "anchor.json"
    p.write_text(json.dumps({"anchor_key": "gpqa_diamond", "native_value": 50.0,
                             "n_items": 198}))
    result = core.ingest_file(str(p), "anchor")
    _assert_comparison(result)
    assert result["anchor"] == "gpqa_diamond"
    assert result["normalized_0_1"] == pytest.approx(0.5)


def test_ingest_file_unknown_fmt_raises(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    with pytest.raises(ValueError):
        core.ingest_file(str(p), "bogus-fmt")


# --------------------------------------------------------------------------- #
# The cross-cutting invariant: EVERY public return path is comparison-mode.
# --------------------------------------------------------------------------- #

def test_every_result_is_non_official(tmp_path):
    tasks, keys = _pack()
    good = [{"xodexa_task_id": t.task_id,
             "resps": [grade.synth_good(keys[t.task_id]["grader"])]} for t in tasks]
    inspect_log = {"samples": [
        {"id": t.task_id, "output": {"completion": grade.synth_good(keys[t.task_id]["grader"])}}
        for t in tasks]}

    results = [
        core.central_rescore(keys, adapters.parse_lm_eval_raw(good), "lm-eval"),
        core.central_rescore(keys, adapters.parse_inspect_log(inspect_log), "inspect"),
        core.anchor_result("mmlu_pro", 72.0, 100, "paper"),
        core.anchor_result("swe_bench_verified", 45.0, 500, "leaderboard"),
    ]
    for r in results:
        _assert_comparison(r)
