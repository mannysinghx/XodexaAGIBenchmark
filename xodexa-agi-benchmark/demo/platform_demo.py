#!/usr/bin/env python3
"""
platform_demo.py — end-to-end demonstration of the Xodexa platform layer.

Unlike e2e_demo.py (which proves the *trust kernel*: signing, tamper-detection,
central re-scoring), this demo exercises the *evaluation science*:

  generate a hidden pack  ->  simulate several models with distinct capability
  profiles  ->  central re-score  ->  Xodexa Score (0-1000)  ->  failure analysis
  ->  AGI Readiness Index + Level  ->  improvement roadmap  ->  signed report,
  then assembles a leaderboard (with HLE-style Rank Upper Bound) and writes the
  JSON the frontend renders.

    python demo/platform_demo.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from xodexa import generators as G, grade, schema, evaluate, report  # noqa: E402
from xodexa.calibration import rank_upper_bound  # noqa: E402
from xodexa.crypto import KeyPair  # noqa: E402

# Simulated models: per-family probability of a correct answer + an over/under
# confidence style. These are toy stand-ins for real connectors (vLLM/OpenAI/...).
MODELS = {
    "frontier-generalist-x": {
        "default": 0.82,
        "by_family": {"safety": 0.86, "agent": 0.74, "memory": 0.9, "code": 0.8},
        "confidence": "calibrated",
    },
    "broad-assistant-7b": {
        "default": 0.55,
        "by_family": {"agent": 0.38, "safety": 0.5, "math": 0.6, "memory": 0.62},
        "confidence": "overconfident",
    },
    "narrow-coder-mini": {
        "default": 0.4,
        "by_family": {"code": 0.78, "math": 0.66, "agent": 0.25, "safety": 0.35,
                      "truthfulness": 0.3},
        "confidence": "overconfident",
    },
    "honest-but-limited": {
        "default": 0.46,
        "by_family": {"truthfulness": 0.8, "safety": 0.72, "agent": 0.3},
        "confidence": "calibrated",
    },
}


def simulate(keys: dict, profile: dict, seed: int) -> list[dict]:
    rng = random.Random(seed)
    responses = []
    for tid, key in keys.items():
        fam = key.get("family", "reasoning")
        p = profile["by_family"].get(fam, profile["default"])
        correct = rng.random() < p
        g = key["grader"]
        out = grade.synth_good(g) if correct else grade.synth_bad(g)
        # confidence model
        if profile["confidence"] == "calibrated":
            conf = rng.uniform(0.6, 0.95) if correct else rng.uniform(0.2, 0.5)
        else:  # overconfident: high confidence regardless of correctness
            conf = rng.uniform(0.8, 0.99)
        responses.append({"id": tid, "output": out, "confidence": round(conf, 3),
                          "latency_ms": rng.uniform(700, 3200),
                          "tokens": max(1, len(out) // 4)})
    return responses


def main():
    signer = KeyPair.generate()
    # one shared hidden pack so models are comparable
    tasks = G.generate(n=180, seed=24680, visibility="private_hidden")
    keys = {t.task_id: schema.answer_key(t) for t in tasks}

    # human baselines (illustrative Layer-5 values, 0..1)
    human_baselines = {f: {"average_human_score": 0.55, "expert_human_score": 0.82}
                       for f in {k["family"] for k in keys.values()}}

    reports = {}
    leaderboard = []
    print("=" * 78)
    print("  XODEXA PLATFORM DEMO — evaluate, score, profile, diagnose")
    print("=" * 78)
    for i, (model_id, profile) in enumerate(MODELS.items()):
        responses = simulate(keys, profile, seed=100 + i)
        er = evaluate.score_pack(keys, responses)
        toks = sum(r["tokens"] for r in responses)
        lat = sum(r["latency_ms"] for r in responses)
        rep = report.build_report(
            model_id, "Xodexa Hidden Official (demo)", er,
            external_signals={"canary_leakage": float(er["canary_hits"]) / max(1, len(keys))},
            telemetry={"tokens": toks, "latency_ms": round(lat),
                       "avg_latency_ms": round(lat / len(responses), 1)},
            human_baselines=human_baselines, signer=signer)
        reports[model_id] = rep
        ar = rep["agi_readiness"]
        leaderboard.append({
            "model": model_id, "xodexa_score": rep["xodexa_score"],
            "grade": rep["grade"], "agi_level": ar["level"],
            "agi_level_name": ar["level_name"],
            "agi_index": ar["agi_readiness_index"],
            "accuracy": rep["frontier_metrics"]["accuracy"],
            "calibration_error": rep["frontier_metrics"]["calibration_error"],
            "ci": rep["frontier_metrics"]["accuracy_ci95"],
            "subscores": ar["subscores"],
            "family_scores": er["family_scores"],
            "contamination_risk": rep["contamination_risk"],
            "time_horizon": rep["time_horizon"]["estimated_task_horizon"],
        })
        print(f"\n  {model_id}")
        print(f"     Xodexa Score : {rep['xodexa_score']}/1000 ({rep['grade']})  "
              f"CI {rep['score_ci95']}")
        print(f"     AGI Readiness: Level {ar['level']} — {ar['level_name']} "
              f"(index {ar['agi_readiness_index']})")
        print(f"     Accuracy     : {rep['frontier_metrics']['accuracy']}% "
              f"± {rep['frontier_metrics']['accuracy_ci95']}  | "
              f"calib err {rep['frontier_metrics']['calibration_error']}")
        print(f"     Top gap      : {ar['missing_capability']}")
        print(f"     Fix at       : {rep['improvement_path']['likely_root_layer']}-level")

    # HLE-style ranking by score significance
    ranked = rank_upper_bound([{"model": e["model"], "score": e["accuracy"],
                                "ci": e["ci"]} for e in leaderboard])
    rank_by_model = {r["model"]: r["rank_ub"] for r in ranked}
    for e in leaderboard:
        e["rank_ub"] = rank_by_model[e["model"]]
    leaderboard.sort(key=lambda e: e["xodexa_score"], reverse=True)

    # write artifacts (results/ + frontend data dir)
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    (out / "platform_leaderboard.json").write_text(
        json.dumps({"benchmark_version": "1.0.0", "entries": leaderboard}, indent=2))
    data_dir = ROOT / "frontend" / "public" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "leaderboard.json").write_text(
        json.dumps({"benchmark_version": "1.0.0", "entries": leaderboard}, indent=2))
    # one full sample report for the /reports page
    sample = leaderboard[0]["model"]
    (out / f"platform_report_{sample}.json").write_text(json.dumps(reports[sample], indent=2))
    (data_dir / "sample_report.json").write_text(json.dumps(reports[sample], indent=2))

    print("\n" + "=" * 78)
    print("  LEADERBOARD (by Xodexa Score)")
    print("  " + "-" * 74)
    print(f"  {'rank':<5}{'model':<26}{'score':>7}{'  grade':<22}{'AGI':>5}")
    for e in leaderboard:
        print(f"  #{e['rank_ub']:<4}{e['model']:<26}{e['xodexa_score']:>7}  "
              f"{e['grade']:<20}L{e['agi_level']}")
    print("=" * 78)
    print(f"  Wrote results/platform_leaderboard.json + frontend/public/data/*.json")
    print(f"  Sample full report: results/platform_report_{sample}.json")
    print("=" * 78)


if __name__ == "__main__":
    main()
