#!/usr/bin/env python3
"""
test_platform.py — contract tests for the Xodexa platform layer.

Runs with pytest OR standalone:  python tests/test_platform.py
Covers: generator validity, the trust boundary, the generation pipeline (contamination
+ signing + no-leak), 12-dimension scoring, the full evaluate->report chain, the AGI
readiness profile, the plugin registry security policy, and the calibration anchors.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))  # beat any shadow 'xodexa'

from xodexa import (generators as G, grade, schema, families, evaluate, report,  # noqa
                    agi_readiness, registry, anchors, scoring)
from xodexa.contamination import CorpusIndex
from xodexa.crypto import KeyPair, verify
from xodexa.pipeline import DatasetPipeline


def test_weights_sum_to_one():
    assert abs(sum(families.SCORE_WEIGHTS.values()) - 1.0) < 1e-9
    assert abs(sum(agi_readiness.SUBSCORE_WEIGHTS.values()) - 1.0) < 1e-9


def test_all_families_have_generators():
    fams = {s.family for s in G.list_generators()}
    assert fams == set(families.FAMILY_KEYS), fams
    assert len(G.list_generators()) >= 50


def test_generators_valid_and_oracle_passes():
    for spec in G.list_generators():
        for t in G.generate_from(spec.generator_id, 2, seed=3, visibility="public"):
            assert schema.is_valid(t), schema.validate_task(t)
            aw, mx, _ = grade.grade(t.server_grader, grade.synth_good(t.server_grader),
                                    t.points, t.negative)
            assert mx and aw >= mx - 1e-6, (spec.generator_id, aw, mx)


def test_trust_boundary_public_view():
    t = G.generate(family="reasoning", n=1, seed=1, visibility="private_hidden")[0]
    assert t.expected_answer is None  # hidden tasks never carry a public answer
    pv = schema.public_view(t)
    assert "expected_answer" not in pv and "server_grader" not in pv
    assert pv["contamination_controls"]["canary"]  # canary retained for echo detection
    ak = schema.answer_key(t)
    assert ak["grader"] and ak["canary"]


def test_pipeline_filters_and_signs():
    tasks = G.generate(n=60, seed=11, visibility="public")
    corpus = CorpusIndex()
    corpus.add("leak", tasks[0].prompt)  # plant a near-duplicate
    rel = DatasetPipeline(corpus=corpus).run(tasks, "T", "0.1.0")
    # contamination filter dropped at least the planted dup
    assert rel.manifest["contamination"]["rejected_for_contamination"] >= 1
    # no answer leaks into shippable views
    assert all("expected_answer" not in t and "server_grader" not in t
               for t in rel.public_tasks)
    # manifest signature verifies
    assert verify(rel.manifest["signer_pub"], rel.manifest, rel.signature)
    assert len(rel.answer_keys) == len(rel.public_tasks)


def test_scoring_covers_twelve_dims():
    # full-credit on every family -> high score, coverage over present dims
    tasks = G.generate(n=48, seed=7, visibility="validation")
    keys = {t.task_id: schema.answer_key(t) for t in tasks}
    responses = [{"id": t.task_id, "output": grade.synth_good(t.server_grader),
                  "confidence": 0.8} for t in tasks]
    er = evaluate.score_pack(keys, responses)
    apex = scoring.apex_score(er["item_results"], weights=families.SCORE_WEIGHTS)
    assert apex["apex_score"] >= 900, apex["apex_score"]
    assert families.grade_band(apex["apex_score"]) in [b[2] for b in families.GRADE_BANDS]


def test_full_report_chain_and_signature():
    tasks = G.generate(n=72, seed=42, visibility="private_hidden")
    keys = {t.task_id: schema.answer_key(t) for t in tasks}
    rng = random.Random(1)
    responses = []
    for t in tasks:
        ok = rng.random() < 0.6
        out = grade.synth_good(t.server_grader) if ok else grade.synth_bad(t.server_grader)
        responses.append({"id": t.task_id, "output": out,
                          "confidence": rng.uniform(0.7, 0.99), "latency_ms": 1500})
    er = evaluate.score_pack(keys, responses)
    rep = report.build_report("m", "pack", er)
    for k in ("xodexa_score", "agi_readiness", "failure_analysis", "improvement_path",
              "verification_appendix", "executive_summary"):
        assert k in rep, k
    ar = rep["agi_readiness"]
    assert 0.0 <= ar["agi_readiness_index"] <= 1.0
    assert 0 <= ar["level"] <= 6
    va = rep["verification_appendix"]
    assert verify(va["signer_pub"], {"body_hash": va["body_sha256"], "model_id": "m",
                                     "xodexa_score": rep["xodexa_score"]}, va["signature"])


def test_registry_security_policy():
    k = KeyPair.generate()
    good = registry.sign_manifest(registry.example_manifest(), k)
    assert registry.validate_manifest(good) == []
    assert registry.PluginRegistry().install(good)["installed"] is True
    # unsigned -> rejected
    assert registry.validate_manifest(registry.example_manifest())
    # network-on after signing -> signature + policy violation
    bad = dict(good); bad["permissions"] = dict(good["permissions"]); bad["permissions"]["network"] = True
    v = registry.validate_manifest(bad)
    assert any("network" in x for x in v)


def test_anchors_normalize_and_separate():
    assert len(anchors.ANCHORS) >= 20
    assert 0.0 <= anchors.normalize_score("mmlu_pro", 72.5) <= 1.0
    summ = anchors.contamination_summary()
    assert sum(summ["by_contamination_risk"].values()) == summ["total_anchors"]


# --------------------------------------------------------------------------- #

def _run_standalone():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ {fn.__name__}  — {e}")
        except Exception as e:  # noqa
            print(f"  ✗ {fn.__name__}  — {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} platform tests passed")
    return 0 if passed == len(fns) else 1


if __name__ == "__main__":
    print("Xodexa platform tests\n" + "-" * 40)
    sys.exit(_run_standalone())
