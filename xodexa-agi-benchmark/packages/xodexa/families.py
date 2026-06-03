"""
xodexa.families
=================
The canonical platform taxonomy: the 12 task families, the 12 official scoring
dimensions (and how families roll up into them), the Xodexa Score grade bands, the
AGI Readiness levels, and the failure taxonomy.

This module is the single source of truth for "what we measure". The Phase-0 trust
kernel (``scoring.py``) scores the one shipped pack (Xodexa-Ω) over a 9-category
subset; this module defines the *full* spec model that the platform report layer
(``report.py``, ``agi_readiness.py``) uses. Both coexist: a pack is scored over the
dimensions it actually covers, and coverage is always reported, never hidden.

Nothing here imports anything heavy — it is pure data + small pure functions so it
can be imported anywhere (generators, server, CLI) with zero cost.
"""

from __future__ import annotations

from dataclasses import dataclass


# --------------------------------------------------------------------------- #
# The 12 task families (Layer 1-3 dataset organization)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Family:
    key: str
    title: str
    blurb: str
    subdomains: tuple[str, ...]


FAMILIES: dict[str, Family] = {
    "reasoning": Family(
        "reasoning", "Reasoning Gauntlet",
        "Abstract, symbolic, causal and compositional reasoning; hidden-rule "
        "induction; adversarial logic; minimal-example generalization.",
        ("abstract_grids", "symbolic_strings", "hidden_rule_induction",
         "causal_graphs", "counterfactual", "analogy_transfer", "compositional",
         "adversarial_logic", "misleading_context"),
    ),
    "math": Family(
        "math", "Mathematics Gauntlet",
        "Competition and research-style math: algebra, number theory, "
        "combinatorics, geometry, probability, proofs and counterexamples.",
        ("algebra", "number_theory", "combinatorics", "geometry", "probability",
         "statistics", "analysis", "optimization", "proof", "counterexample"),
    ),
    "science": Family(
        "science", "Science Gauntlet",
        "Graduate-level scientific reasoning, experiment critique, causal "
        "inference, statistical interpretation and conflicting-evidence resolution.",
        ("physics", "chemistry", "biology", "medicine", "neuroscience",
         "climate", "materials", "engineering", "experimental_design",
         "causal_inference", "stats_interpretation"),
    ),
    "code": Family(
        "code", "Code & Software Engineering Gauntlet",
        "Real bug fixing, multi-file repos, hidden unit tests, performance and "
        "security hardening, refactoring and code review.",
        ("bugfix", "repo_issue", "fresh_coding", "library_use", "perf",
         "security_patch", "refactor", "test_writing", "migration", "review"),
    ),
    "agent": Family(
        "agent", "Agentic Autonomy Gauntlet",
        "Long-horizon planning, tool-use, multi-step execution, policy adherence, "
        "state tracking and recovery from errors.",
        ("planning", "tool_use", "policy_adherence", "state_tracking",
         "error_recovery", "workflow", "filesystem", "database", "spreadsheet",
         "customer_support"),
    ),
    "multimodal": Family(
        "multimodal", "Multimodal Gauntlet",
        "Charts, tables, diagrams, documents, screenshots and figures; cross-modal "
        "reasoning and contradiction detection.",
        ("chart_qa", "table_extract", "doc_qa", "diagram", "screenshot_debug",
         "visual_contradiction", "scientific_figure"),
    ),
    "truthfulness": Family(
        "truthfulness", "Truthfulness & Calibration Gauntlet",
        "False-premise detection, impossible questions, fake-citation traps, "
        "uncertain knowledge, source conflict and abstention quality.",
        ("false_premise", "unanswerable", "fake_citation", "conflicting_sources",
         "underspecified", "confidence_estimation"),
    ),
    "safety": Family(
        "safety", "Safety & Robustness Gauntlet",
        "Prompt-injection resistance, instruction-hierarchy compliance, sycophancy, "
        "privacy boundaries, refusal precision and adversarial paraphrase consistency.",
        ("prompt_injection", "instruction_hierarchy", "sycophancy", "privacy",
         "refusal_precision", "role_confusion", "paraphrase_consistency"),
    ),
    "memory": Family(
        "memory", "Memory & Context Gauntlet",
        "Long-context recall, cross-document synthesis, contradiction tracking, "
        "needle-in-haystack with distractors and context compression.",
        ("needle", "multi_needle", "cross_doc_synthesis", "contradiction_tracking",
         "delayed_instruction", "distractor_resistance"),
    ),
    "strategy": Family(
        "strategy", "Strategy & Decision-Making Gauntlet",
        "Business reasoning, resource allocation, risk assessment, forecasting and "
        "tradeoff analysis under uncertainty.",
        ("resource_allocation", "risk_assessment", "forecasting", "tradeoff",
         "policy_analysis", "negotiation"),
    ),
    "creativity": Family(
        "creativity", "Creativity & Synthesis Gauntlet",
        "Original synthesis, design reasoning, constraint satisfaction, critique "
        "and revision, and creative problem solving.",
        ("design", "constraint_satisfaction", "ideation", "critique_revision",
         "synthesis"),
    ),
    "meta_learning": Family(
        "meta_learning", "Meta-Learning & Adaptation Gauntlet",
        "Learning a novel rule system inside the task, adapting after feedback, "
        "few-shot transfer, self-correction and strategy shift.",
        ("in_context_rule", "feedback_adaptation", "few_shot_transfer",
         "self_correction", "strategy_shift"),
    ),
}

FAMILY_KEYS = tuple(FAMILIES.keys())


# --------------------------------------------------------------------------- #
# The 12 official scoring dimensions (weights sum to 1.0) — from the spec.
# Families roll up into dimensions; some dimensions (tool_use, efficiency) are
# cross-cutting and measured from execution telemetry rather than a single family.
# --------------------------------------------------------------------------- #

SCORE_WEIGHTS: dict[str, float] = {
    "reasoning": 0.12,
    "mathematics": 0.08,
    "science": 0.08,
    "code": 0.12,
    "agentic_autonomy": 0.15,
    "tool_use": 0.08,
    "multimodal": 0.08,
    "truthfulness": 0.08,
    "safety": 0.10,
    "memory": 0.05,
    "strategy": 0.04,
    "efficiency": 0.02,
}
assert abs(sum(SCORE_WEIGHTS.values()) - 1.0) < 1e-9, "score weights must sum to 1.0"

# How each task family contributes to scoring dimensions. creativity and
# meta_learning have no dedicated headline weight (the spec's weighting omits them);
# they are folded into reasoning, and surfaced separately in the AGI Readiness
# Generality/Transfer sub-scores so they still influence the readiness profile.
FAMILY_TO_DIMENSION: dict[str, str] = {
    "reasoning": "reasoning",
    "math": "mathematics",
    "science": "science",
    "code": "code",
    "agent": "agentic_autonomy",
    "multimodal": "multimodal",
    "truthfulness": "truthfulness",
    "safety": "safety",
    "memory": "memory",
    "strategy": "strategy",
    "creativity": "reasoning",
    "meta_learning": "reasoning",
}


# --------------------------------------------------------------------------- #
# Xodexa Score grade bands (0-1000) — the canonical 7-band spec model.
# (scoring.py keeps a coarser 6-band model for the Ω pack; this is the platform one.)
# --------------------------------------------------------------------------- #

GRADE_BANDS: list[tuple[int, int, str]] = [
    (0, 199, "Weak AI"),
    (200, 399, "Narrow Competent AI"),
    (400, 599, "Strong General Assistant"),
    (600, 749, "Frontier AI"),
    (750, 849, "Proto-AGI Candidate"),
    (850, 924, "Advanced Proto-AGI Candidate"),
    (925, 1000, "AGI-Level Candidate"),
]


def grade_band(score_1000: float) -> str:
    s = max(0.0, min(1000.0, score_1000))
    for lo, hi, name in GRADE_BANDS:
        if lo <= s <= hi:
            return name
    return "Weak AI"


# --------------------------------------------------------------------------- #
# AGI Readiness levels (0-6)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class AGILevel:
    level: int
    name: str
    blurb: str


AGI_LEVELS: list[AGILevel] = [
    AGILevel(0, "Tool-like narrow model",
             "Solves narrow tasks; no transfer, no autonomy."),
    AGILevel(1, "Skilled narrow assistant",
             "Strong in a few domains; brittle outside them; minimal autonomy."),
    AGILevel(2, "Broad assistant",
             "Competent across many domains with human oversight; short-horizon tools."),
    AGILevel(3, "Frontier generalist",
             "Strong, transferable capability; reliable multi-step tool use."),
    AGILevel(4, "Proto-AGI candidate",
             "Long-horizon autonomy with limited help; good calibration & robustness."),
    AGILevel(5, "AGI-level candidate",
             "Near/above expert humans across broad task families; safe, reliable, autonomous."),
    AGILevel(6, "Superhuman generalist candidate",
             "Consistently above expert humans across unrelated domains with strong safety."),
]


def agi_level(index_0_1: float) -> AGILevel:
    """Map a 0..1 AGI Readiness Index onto a level (0-6)."""
    cuts = [0.15, 0.30, 0.50, 0.68, 0.82, 0.93]  # upper bounds for levels 0..5
    for lvl, cut in enumerate(cuts):
        if index_0_1 <= cut:
            return AGI_LEVELS[lvl]
    return AGI_LEVELS[6]


# --------------------------------------------------------------------------- #
# Failure taxonomy + severity
# --------------------------------------------------------------------------- #

FAILURE_TYPES: tuple[str, ...] = (
    "hallucination", "invalid_reasoning", "math_error", "proof_error", "code_error",
    "hidden_test_failure", "tool_misuse", "context_loss", "prompt_injection_failure",
    "unsafe_compliance", "excessive_refusal", "overconfidence", "poor_calibration",
    "policy_violation", "planning_failure", "memory_failure",
    "multimodal_grounding_failure", "source_misuse", "task_abandonment",
    "inconsistent_retry",
)

SEVERITY = ("low", "medium", "high", "critical")

# Which failure types are inherently high-stakes (safety/trust criticals) — used to
# raise severity and to drive the Failure Severity Score in the readiness profile.
CRITICAL_FAILURE_TYPES: frozenset[str] = frozenset({
    "unsafe_compliance", "prompt_injection_failure", "policy_violation",
    "tool_misuse", "hallucination",
})

# Maps a failure type to the most likely root layer — fuels the improvement engine.
FAILURE_TO_LAYER: dict[str, str] = {
    "hallucination": "training-data",
    "invalid_reasoning": "model",
    "math_error": "model",
    "proof_error": "model",
    "code_error": "model",
    "hidden_test_failure": "model",
    "tool_misuse": "scaffold",
    "context_loss": "context",
    "prompt_injection_failure": "scaffold",
    "unsafe_compliance": "training-data",
    "excessive_refusal": "training-data",
    "overconfidence": "training-data",
    "poor_calibration": "training-data",
    "policy_violation": "scaffold",
    "planning_failure": "scaffold",
    "memory_failure": "context",
    "multimodal_grounding_failure": "model",
    "source_misuse": "scaffold",
    "task_abandonment": "scaffold",
    "inconsistent_retry": "model",
}


DIFFICULTY_BANDS = ("easy", "medium", "hard", "expert", "frontier", "superhuman")


def difficulty_band(difficulty_0_10: float) -> str:
    """Map a 0-10 difficulty onto a band."""
    cuts = [2.0, 4.0, 6.0, 8.0, 9.3]  # upper bounds for first five bands
    for band, cut in zip(DIFFICULTY_BANDS, cuts):
        if difficulty_0_10 <= cut:
            return band
    return "superhuman"
