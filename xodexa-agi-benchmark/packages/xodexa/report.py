"""
xodexa.report
===============
Assembles the full evaluation report from centrally-scored results and signs it. This
is the artifact a lab/researcher actually reads: executive summary, Xodexa Score, AGI
Readiness Index + Level, per-category breakdown, human-baseline comparison, hardest
and critical failures, contamination risk, reliability, cost/latency, time-horizon
estimate, the model improvement path, recommended next benchmarks, a raw-results
appendix and a cryptographic verification appendix.

``build_report`` is the one entry point: feed it the output of ``evaluate.score_pack``
plus context and it returns a signed, self-describing report dict.
"""

from __future__ import annotations

import time

from . import scoring, failure_analysis, agi_readiness, improvement, families
from .crypto import KeyPair, sha256_hex


def estimate_time_horizon(family_scores: dict, per_item: list[dict]) -> dict:
    """Rough 'how long a task can it autonomously complete' estimate, anchored on the
    agent + memory families (long-horizon proxies) and average item difficulty solved."""
    agent = family_scores.get("agent", 0.0)
    memory = family_scores.get("memory", 0.0)
    horizon = 0.6 * agent + 0.4 * memory
    # map 0..1 onto a human-minutes scale (log-ish bands)
    bands = [(0.2, "< 1 min (single step)"), (0.4, "~1-5 min (few steps)"),
             (0.6, "~5-30 min (short multi-step task)"),
             (0.8, "~30-120 min (substantial task)"),
             (1.01, "multi-hour autonomous task")]
    label = next(lbl for cut, lbl in bands if horizon <= cut)
    return {"horizon_score": round(horizon, 3), "estimated_task_horizon": label}


def build_report(model_id: str, pack_name: str, eval_result: dict, *,
                 external_signals: dict | None = None, telemetry: dict | None = None,
                 human_baselines: dict | None = None, reliability: float | None = None,
                 benchmark_version: str = "1.0.0", contamination_risk: float | None = None,
                 signer: KeyPair | None = None) -> dict:
    signer = signer or KeyPair.generate()
    external_signals = external_signals or {}
    telemetry = telemetry or {}

    item_results = eval_result["item_results"]
    per_item = eval_result["per_item"]
    family_scores = eval_result["family_scores"]
    frontier = eval_result["frontier_metrics"]

    # 1. Xodexa Score (0-1000) — central scoring with external penalties, over the
    #    canonical 12 spec dimensions (not the Ω pack's 9-category subset).
    apex = scoring.apex_score(item_results, external_signals=external_signals,
                              weights=families.SCORE_WEIGHTS)
    # platform-canonical 7-band grade (families.grade_band) alongside scoring.py's band
    platform_grade = families.grade_band(apex["apex_score"])

    # 2. Failure ledger.
    failures = failure_analysis.classify_failures(per_item)

    # 3. AGI Readiness profile.
    readiness = agi_readiness.build_profile(
        family_scores, frontier_metrics=frontier, failures=failures,
        reliability=reliability, human_baselines=human_baselines, telemetry=telemetry)

    # 4. Improvement roadmap.
    roadmap = improvement.build_roadmap(readiness, failures, family_scores)

    # 5. Reliability + time horizon.
    horizon = estimate_time_horizon(family_scores, per_item)

    # 6. Human-baseline comparison.
    hb = _human_comparison(family_scores, human_baselines)

    # contamination risk: prefer explicit, else infer from external signals.
    if contamination_risk is None:
        contamination_risk = round(min(1.0,
            0.5 * float(external_signals.get("canary_leakage", 0.0))
            + 0.3 * float(external_signals.get("contamination_risk", 0.0))
            + 0.2 * float(external_signals.get("timing_anomaly", 0.0))), 3)

    summary = (
        f"{model_id} scored {apex['apex_score']}/1000 ({platform_grade}) on "
        f"{pack_name}, placing it at AGI Readiness Level {readiness['level']} "
        f"({readiness['level_name']}). {readiness['missing_capability']} "
        f"Failure rate {failures['failure_rate']:.0%} over {failures['total_items']} "
        f"items; {len(failures['critical_failures'])} critical. "
        f"{roadmap['headline']}"
    )

    report = {
        "report_version": "1.0",
        "generated_at": _iso(time.time()),
        "model_id": model_id,
        "pack": pack_name,
        "benchmark_version": benchmark_version,
        "executive_summary": summary,
        "xodexa_score": apex["apex_score"],
        "grade": platform_grade,
        "grade_legacy": apex["grade"],
        "score_ci95": apex["ci95"],
        "coverage": apex["coverage_label"],
        # Coverage-aware, anti-gaming numbers: the adjusted score discounts unproven
        # dimensions; `provisional` marks a run that exercised too little of the benchmark
        # to be ranked head-to-head against full runs.
        "coverage_fraction": apex["coverage"],
        "covered_weight_fraction": apex["covered_weight_fraction"],
        "coverage_adjusted_score": apex["coverage_adjusted_score"],
        "provisional": apex["provisional"],
        "category_breakdown": apex["categories"],
        "categories_not_evaluated": apex["categories_not_evaluated"],
        # Honest caveats for any scored dimension measured via a proxy (e.g. multimodal is
        # text-rendered, not real vision) — so the number isn't read as the full capability.
        "measurement_caveats": {d: note for d, note in families.PROXY_DIMENSIONS.items()
                                if d in apex["categories"]},
        "external_penalties": apex["external_penalties_applied"],
        "frontier_metrics": frontier,
        "agi_readiness": readiness,
        "failure_analysis": {k: v for k, v in failures.items() if k != "failures"},
        "human_baseline_comparison": hb,
        "reliability_score": readiness["subscores"]["reliability"],
        "time_horizon": horizon,
        "contamination_risk": contamination_risk,
        "cost_latency": _cost_latency(telemetry),
        "improvement_path": roadmap,
        "next_recommended_benchmarks": roadmap["recommended_next_evals"][:6],
        "raw_results_appendix": per_item,
        "_failures_detail": failures["failures"],
    }

    # Cryptographic verification appendix — sign the report body.
    body_hash = sha256_hex({k: v for k, v in report.items()
                            if k not in ("raw_results_appendix", "_failures_detail")})
    signature = signer.sign({"body_hash": body_hash, "model_id": model_id,
                             "xodexa_score": report["xodexa_score"]})
    report["verification_appendix"] = {
        "body_sha256": body_hash,
        "signer_pub": signer.pub_b64,
        "signature": signature,
        "note": "Signature covers the report body (excluding bulky appendices). "
                "Official scores are issued only by the central authority "
                "(authority.ScoringAuthority), never by a self-hosted runner.",
    }
    return report


def _human_comparison(family_scores: dict, human_baselines: dict | None) -> dict:
    if not human_baselines:
        return {"available": False,
                "note": "No human baselines collected yet for this pack (Layer 5)."}
    rows = []
    for fam, score in sorted(family_scores.items()):
        hb = human_baselines.get(fam) or {}
        rows.append({
            "family": fam, "model": round(score, 3),
            "average_human": hb.get("average_human_score"),
            "expert_human": hb.get("expert_human_score"),
            "verdict": _parity_verdict(score, hb),
        })
    return {"available": True, "rows": rows}


def _parity_verdict(score, hb) -> str:
    exp = hb.get("expert_human_score")
    avg = hb.get("average_human_score")
    if exp is not None and score >= exp:
        return "at/above expert"
    if avg is not None and score >= avg:
        return "at/above average human"
    if avg is not None:
        return "below average human"
    return "no baseline"


def _cost_latency(telemetry: dict) -> dict:
    return {
        "total_tokens": telemetry.get("tokens"),
        "total_latency_ms": telemetry.get("latency_ms"),
        "cost_usd": telemetry.get("cost_usd"),
        "avg_latency_ms_per_task": telemetry.get("avg_latency_ms"),
    }


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))
