"""
xodexa.improvement
====================
The model improvement-path engine — the "Path to AGI Capability Report". The platform
should not only score a model, it should diagnose how to make it better. Given the AGI
Readiness profile + failure ledger + per-family scores, this produces a structured,
actionable roadmap: strengths, weaknesses, highest-severity failure modes, capability
bottlenecks, gap categories, recommended next evals / fine-tuning data / RL targets /
scaffolding changes, and — crucially — whether each failure is most likely model-,
scaffold-, tool-, context-, or training-data-level.

Pure rule-based synthesis over the upstream signals; deterministic and auditable.
"""

from __future__ import annotations

from . import families

# Recommendation libraries keyed by the lagging sub-score.
_RECS = {
    "generality": {
        "eval": ["broaden coverage across all 12 families", "cross-domain transfer suite"],
        "data": ["diverse multi-domain instruction data", "under-covered family corpora"],
        "rl": ["reward breadth, not just peak-domain accuracy"],
        "scaffold": ["route by domain to specialist prompts/tools"],
    },
    "autonomy": {
        "eval": ["GAIA-style tool workflows", "tau-bench policy conversations",
                 "long-horizon multi-step agent tasks"],
        "data": ["successful long-horizon trajectories", "task-decomposition traces"],
        "rl": ["process rewards for subgoal completion", "penalize abandonment"],
        "scaffold": ["explicit planner/executor split", "persistent state store",
                     "tool-call validation + retries"],
    },
    "reliability": {
        "eval": ["repeat each task k times, score consistency", "perturbation/paraphrase suite"],
        "data": ["self-consistency / verification traces"],
        "rl": ["reward agreement across sampled rollouts"],
        "scaffold": ["self-check / verifier loop", "majority-vote over samples"],
    },
    "transfer": {
        "eval": ["meta-learning / in-context-rule suite", "ARC-style novel reasoning"],
        "data": ["procedurally-novel rule-learning tasks"],
        "rl": ["reward few-shot adaptation, not memorized patterns"],
        "scaffold": ["explicit hypothesize-test loop on novel rules"],
    },
    "grounding": {
        "eval": ["long-context needle + cross-doc synthesis", "multimodal grounding suite"],
        "data": ["citation-grounded answers", "retrieval-augmented traces"],
        "rl": ["reward evidence use; penalize ungrounded claims"],
        "scaffold": ["retrieval + quote-then-answer", "force source attribution"],
    },
    "safety": {
        "eval": ["prompt-injection battery", "instruction-hierarchy + privacy tests"],
        "data": ["benign injection-resistance examples", "policy-hierarchy demonstrations"],
        "rl": ["heavily penalize unsafe compliance and policy violations"],
        "scaffold": ["input/output guardrails", "tool-permission policy engine (OPA)"],
    },
    "calibration": {
        "eval": ["confidence-elicitation + RMS-CE tracking", "unanswerable/abstention suite"],
        "data": ["abstention-positive examples", "uncertainty-expression data"],
        "rl": ["proper-scoring-rule reward on stated confidence"],
        "scaffold": ["confidence threshold -> abstain/escalate"],
    },
    "economic_usefulness": {
        "eval": ["SWE-bench-style repo issues", "real spreadsheet/CRM workflows"],
        "data": ["high-quality code-fix and ops-workflow trajectories"],
        "rl": ["reward passing hidden unit tests + final-state correctness"],
        "scaffold": ["code execution sandbox + test feedback loop"],
    },
    "human_parity": {
        "eval": ["expert-baselined hard subsets", "frontier-difficulty bands only"],
        "data": ["expert-authored solutions on hardest items"],
        "rl": ["curriculum toward expert-band difficulty"],
        "scaffold": ["expert-tool augmentation (solvers, search)"],
    },
    "failure_severity": {
        "eval": ["critical-failure stress tests", "safety red-team battery"],
        "data": ["counterexamples for the observed critical failure modes"],
        "rl": ["asymmetric penalty on high-severity errors"],
        "scaffold": ["hard guardrails + human-in-the-loop on high-stakes actions"],
    },
}

_LAYER_ADVICE = {
    "model": "weights/training — improve via fine-tuning data and RL targets below.",
    "scaffold": "agent scaffolding — fixable without retraining (planner, validators, loops).",
    "tool": "tool layer — the tools/connectors are the bottleneck, not the model.",
    "context": "context handling — long-context / retrieval / state management.",
    "training-data": "training-data — behavioral patterns (honesty, refusal, overconfidence).",
}


def build_roadmap(readiness: dict, failures: dict, family_scores: dict) -> dict:
    sub = readiness["subscores"]
    ranked = sorted(sub.items(), key=lambda kv: kv[1])
    laggards = [k for k, v in ranked if v < 0.55][:5] or [ranked[0][0]]
    strengths = [k for k, v in sorted(sub.items(), key=lambda kv: -kv[1]) if v >= 0.55][:4]

    # Aggregate recommendations from the lagging sub-scores (dedup, preserve intent).
    rec = {"next_evals": [], "fine_tuning_data": [], "rl_targets": [], "scaffolding": []}
    for k in laggards:
        lib = _RECS.get(k, {})
        rec["next_evals"] += lib.get("eval", [])
        rec["fine_tuning_data"] += lib.get("data", [])
        rec["rl_targets"] += lib.get("rl", [])
        rec["scaffolding"] += lib.get("scaffold", [])
    rec = {k: _dedup(v) for k, v in rec.items()}

    # Where do failures most likely originate?
    by_layer = failures.get("by_root_layer", {})
    dominant_layer = max(by_layer, key=by_layer.get) if by_layer else "model"
    layer_breakdown = [
        {"layer": L, "count": c, "interpretation": _LAYER_ADVICE.get(L, "")}
        for L, c in sorted(by_layer.items(), key=lambda kv: -kv[1])
    ]

    # Weakest families (capability bottlenecks).
    weak_families = sorted(family_scores.items(), key=lambda kv: kv[1])[:4]
    bottlenecks = [
        {"family": f, "title": families.FAMILIES[f].title if f in families.FAMILIES else f,
         "score": round(v, 3)} for f, v in weak_families
    ]

    return {
        "headline": _headline(readiness, dominant_layer),
        "current_strengths": [_label(k) for k in strengths] or ["(none above threshold)"],
        "current_weaknesses": [_label(k) for k in laggards],
        "highest_severity_failure_modes": [
            {"failure_type": f["failure_type"], "family": f["family"],
             "severity": f["severity"], "root_layer": f["root_layer"]}
            for f in failures.get("hardest_failures", [])[:5]
        ],
        "capability_bottlenecks": bottlenecks,
        "gap_categories": _gap_categories(sub),
        "likely_root_layer": dominant_layer,
        "root_layer_breakdown": layer_breakdown,
        "recommended_next_evals": rec["next_evals"],
        "recommended_fine_tuning_data": rec["fine_tuning_data"],
        "recommended_rl_targets": rec["rl_targets"],
        "recommended_scaffolding_improvements": rec["scaffolding"],
    }


def _headline(readiness, layer) -> str:
    lvl = readiness["level_name"]
    gap = readiness["missing_capability"]
    return (f"Assessed at {lvl}. {gap} Most failures appear {layer}-level — "
            f"{_LAYER_ADVICE.get(layer, '')}")


def _gap_categories(sub: dict) -> list[dict]:
    mapping = {
        "reasoning_gap": sub["transfer"],
        "memory_gap": sub["grounding"],
        "planning_gap": sub["autonomy"],
        "tool_use_gap": sub["autonomy"],
        "safety_gap": sub["safety"],
        "reliability_gap": sub["reliability"],
        "calibration_gap": sub["calibration"],
        "domain_knowledge_gap": sub["human_parity"],
    }
    out = []
    for name, val in sorted(mapping.items(), key=lambda kv: kv[1]):
        out.append({"gap": name, "severity": _sev(val), "signal": round(val, 3)})
    return out


def _sev(v: float) -> str:
    return "critical" if v < 0.3 else "high" if v < 0.5 else "medium" if v < 0.7 else "low"


_LABELS = {
    "generality": "Generality", "autonomy": "Autonomy", "reliability": "Reliability",
    "transfer": "Transfer", "grounding": "Grounding", "safety": "Safety",
    "calibration": "Calibration", "economic_usefulness": "Economic Usefulness",
    "human_parity": "Human-Parity", "failure_severity": "Failure-Severity",
}


def _label(k: str) -> str:
    return _LABELS.get(k, k)


def _dedup(seq: list) -> list:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
