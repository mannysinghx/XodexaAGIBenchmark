"""
xodexa.evaluate
=================
Central re-scoring for Xodexa-generated packs (the generators/pipeline output), the
analogue of ``suites.grade_response`` for the Ω pack but self-contained on
``xodexa.grade``. Given server-held answer keys and raw runner responses it produces
everything the report layer needs:

  * ``item_results``    — for ``scoring.apex_score`` (the 0-1000 Xodexa Score).
  * ``per_item``        — enriched rows (family, subdomain, difficulty, verdict) for
                          failure analysis.
  * ``family_scores``   — 0..1 per task family (for the AGI Readiness profile).
  * ``frontier_metrics``— HLE-style accuracy ± CI and RMS calibration error.

All scoring happens here, centrally, from RAW outputs — the runner never had the keys.
"""

from __future__ import annotations

from . import grade, families
from .calibration import wilson_ci, rms_calibration_error


def score_pack(answer_keys: dict, responses: list[dict]) -> dict:
    by_id = {r["id"]: r for r in responses}
    item_results: list[dict] = []
    per_item: list[dict] = []
    fam_agg: dict[str, list] = {}           # family -> [awarded, max]
    correct_flags: list[int] = []
    confidences: list[float] = []
    canary_hits = 0

    for tid, key in answer_keys.items():
        resp = by_id.get(tid, {}) or {}
        output = resp.get("output", "")
        aw, mx, verdict = grade.grade(key["grader"], output, key["points"], key["negative"])
        category = key.get("category") or families.FAMILY_TO_DIMENSION.get(
            key.get("family", "reasoning"), "reasoning")
        item_results.append({"category": category, "awarded": aw, "max": mx})
        per_item.append({
            "task_id": tid, "family": key.get("family", "reasoning"),
            "subdomain": key.get("subdomain", ""), "category": category,
            "difficulty": key.get("difficulty", 5.0), "awarded": round(aw, 3),
            "max": mx, "verdict": verdict,
        })
        fam = key.get("family", "reasoning")
        fam_agg.setdefault(fam, [0.0, 0.0])
        fam_agg[fam][0] += aw
        fam_agg[fam][1] += mx

        correct_flags.append(1 if (mx and aw >= 0.5 * mx) else 0)
        if "confidence" in resp:
            confidences.append(float(resp["confidence"]))
        if key.get("canary") and key["canary"] in (output or ""):
            canary_hits += 1

    family_scores = {f: max(0.0, a / m) if m else 0.0 for f, (a, m) in fam_agg.items()}

    n = len(correct_flags)
    acc_point, acc_half, _ = wilson_ci(sum(correct_flags), n)
    calib_err = (rms_calibration_error(confidences, correct_flags)
                 if confidences and len(confidences) == n else None)

    return {
        "item_results": item_results,
        "per_item": per_item,
        "family_scores": family_scores,
        "frontier_metrics": {"accuracy": acc_point, "accuracy_ci95": acc_half,
                             "calibration_error": calib_err, "n": n},
        "canary_hits": canary_hits,
    }
