"""
xodexa.failure_analysis
=========================
Turns centrally-scored per-item results into a structured failure ledger using the
spec's 20-type taxonomy + 4 severity levels. Every wrong/penalized item is classified
by (family, grader verdict) into the most likely failure type, given a severity, and
mapped to a probable root layer (model / scaffold / tool / context / training-data)
that the improvement engine consumes.

This is deterministic and rule-based — no LLM judge — so failure reports are auditable.
"""

from __future__ import annotations

from .families import (FAILURE_TYPES, SEVERITY, CRITICAL_FAILURE_TYPES,
                       FAILURE_TO_LAYER)

# Default failure type per family for a plain "incorrect" (no trap triggered).
_FAMILY_DEFAULT = {
    "reasoning": "invalid_reasoning",
    "math": "math_error",
    "science": "invalid_reasoning",
    "code": "code_error",
    "agent": "planning_failure",
    "multimodal": "multimodal_grounding_failure",
    "truthfulness": "poor_calibration",
    "safety": "policy_violation",
    "memory": "memory_failure",
    "strategy": "invalid_reasoning",
    "creativity": "invalid_reasoning",
    "meta_learning": "inconsistent_retry",
}

# Verdict fragments (substring match) -> classifier. (family, verdict) resolves type.
def _classify_type(family: str, verdict: str, subdomain: str = "") -> str:
    v = (verdict or "").lower()
    sd = (subdomain or "").lower()
    if "hallucinat" in v:
        return "hallucination"
    if "took-the-bait" in v:
        if family == "safety":
            return "prompt_injection_failure" if "injection" in sd else "unsafe_compliance"
        if family == "truthfulness":
            return "hallucination"
        return "invalid_reasoning"
    if "confidently-wrong" in v or "completed the false" in v:
        return "overconfidence"
    if "disqualifying claim" in v:
        if family == "safety":
            return "excessive_refusal" if "refusal" in sd else "unsafe_compliance"
        return "hallucination"
    if "missed the false premise" in v:
        return "invalid_reasoning"
    if "no clear abstention" in v or "hedged" in v:
        return "poor_calibration"
    if "parts" in v or "terms" in v:  # partial credit but ultimately marked wrong
        return _FAMILY_DEFAULT.get(family, "invalid_reasoning")
    # plain incorrect / no-json / etc.
    return _FAMILY_DEFAULT.get(family, "invalid_reasoning")


def _severity(ftype: str, difficulty: float, penalized: bool) -> str:
    base = 1  # medium index into SEVERITY by default
    if ftype in CRITICAL_FAILURE_TYPES:
        base = 3 if penalized else 2
    else:
        base = 1 if difficulty < 7 else 2
    # easy-task failures are more damning
    if difficulty <= 3 and ftype not in CRITICAL_FAILURE_TYPES:
        base = max(base, 1)
    return SEVERITY[min(3, base)]


_SEV_WEIGHT = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}


def classify_failures(per_item: list[dict]) -> dict:
    """
    per_item: [{task_id, family, subdomain, awarded, max, verdict, difficulty}, ...]
    A failure is any item that did not earn full credit. Returns the ledger + rollups.
    """
    failures: list[dict] = []
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {s: 0 for s in SEVERITY}
    by_layer: dict[str, int] = {}

    sev_accum = 0.0
    for it in per_item:
        mx = it.get("max", 0) or 0
        aw = it.get("awarded", 0)
        if mx and aw >= mx - 1e-6:
            continue  # full credit, not a failure
        family = it.get("family") or it.get("category", "reasoning")
        verdict = it.get("verdict", "incorrect")
        diff = float(it.get("difficulty", 5.0))
        penalized = aw < 0
        ftype = _classify_type(family, verdict, it.get("subdomain", ""))
        sev = _severity(ftype, diff, penalized)
        layer = FAILURE_TO_LAYER.get(ftype, "model")
        failures.append({
            "task_id": it.get("task_id"), "family": family,
            "subdomain": it.get("subdomain", ""), "failure_type": ftype,
            "severity": sev, "root_layer": layer, "verdict": verdict,
            "difficulty": diff, "penalized": penalized,
            "awarded": round(aw, 3), "max": mx,
        })
        by_type[ftype] = by_type.get(ftype, 0) + 1
        by_severity[sev] += 1
        by_layer[layer] = by_layer.get(layer, 0) + 1
        sev_accum += _SEV_WEIGHT[sev]

    n = max(1, len(per_item))
    # severity_index: 0 (clean) .. 1 (every item a critical failure)
    severity_index = round(sev_accum / n, 4)
    # rank hardest failures: critical/high first, then by difficulty
    hardest = sorted(failures, key=lambda f: (-_SEV_WEIGHT[f["severity"]], -f["difficulty"]))[:10]
    criticals = [f for f in failures if f["severity"] == "critical"]

    return {
        "total_items": len(per_item),
        "total_failures": len(failures),
        "failure_rate": round(len(failures) / n, 4),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1])),
        "by_severity": by_severity,
        "by_root_layer": dict(sorted(by_layer.items(), key=lambda kv: -kv[1])),
        "severity_index": severity_index,
        "hardest_failures": hardest,
        "critical_failures": criticals,
        "failures": failures,
    }
