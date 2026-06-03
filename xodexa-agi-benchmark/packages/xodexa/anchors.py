"""
xodexa.anchors
================
Layer 0 — Public Calibration Benchmarks. These are public, industry-standard
benchmarks used ONLY to calibrate and contextualize, never as the official Xodexa
hidden score. Each anchor carries its license, the Xodexa dimension(s) it informs, a
**contamination-risk label** (old public sets are likely in training data), and a
normalization rule so an external score maps onto the 0..1 capability scale.

Legal rule (spec "Critical legal and safety rule"): we do NOT ship the benchmark
content. An anchor is metadata + an *adapter contract*. Importing the actual data is
the operator's responsibility, under that benchmark's own license, via the named
loader (e.g. Hugging Face Datasets). This module is the registry + normalizer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Anchor:
    key: str
    name: str
    dimension: str            # Xodexa SCORE_WEIGHTS dimension it informs
    license: str
    contamination_risk: str   # low | medium | high  (high == old/widely-trained-on)
    metric: str               # native metric name
    normalize: str            # how native score maps to 0..1
    loader: str               # how an operator would load it (not shipped)
    notes: str = ""


# Public anchors. Scores from these appear SEPARATELY and never as the Xodexa Score.
ANCHORS: dict[str, Anchor] = {a.key: a for a in [
    Anchor("mmlu_pro", "MMLU-Pro", "reasoning", "MIT", "high", "accuracy",
           "accuracy/100", "hf:TIGER-Lab/MMLU-Pro", "10-choice harder MMLU."),
    Anchor("gpqa_diamond", "GPQA Diamond", "science", "CC-BY-4.0", "medium", "accuracy",
           "accuracy/100", "hf:Idavidrein/gpqa", "Graduate-level google-proof QA."),
    Anchor("hle", "Humanity's Last Exam (style)", "reasoning", "see-source", "low",
           "accuracy", "accuracy/100", "hf:cais/hle",
           "Expert frontier exam; calibration error is the key honesty signal."),
    Anchor("frontiermath", "FrontierMath (style)", "mathematics", "see-source", "low",
           "accuracy", "accuracy/100", "see-source", "Research-level math; very hard."),
    Anchor("swe_bench_verified", "SWE-bench Verified", "code", "MIT", "medium",
           "resolved_rate", "resolved/100", "hf:princeton-nlp/SWE-bench_Verified",
           "Real GitHub issues; hidden tests."),
    Anchor("livecodebench", "LiveCodeBench", "code", "CC", "low", "pass@1",
           "pass_at_1", "hf:livecodebench/code_generation",
           "Time-windowed fresh problems → low contamination."),
    Anchor("bigcodebench", "BigCodeBench", "code", "Apache-2.0", "medium", "pass@1",
           "pass_at_1", "hf:bigcode/bigcodebench", "Library-use coding."),
    Anchor("humaneval", "HumanEval", "code", "MIT", "high", "pass@1", "pass_at_1",
           "hf:openai_humaneval", "Saturated/contaminated — calibration only."),
    Anchor("gsm8k", "GSM8K", "mathematics", "MIT", "high", "accuracy", "accuracy/100",
           "hf:openai/gsm8k", "Grade-school math; largely saturated."),
    Anchor("math", "MATH", "mathematics", "MIT", "high", "accuracy", "accuracy/100",
           "hf:hendrycks/competition_math", "Competition math."),
    Anchor("aime", "AIME (style)", "mathematics", "see-source", "medium", "accuracy",
           "accuracy/100", "see-source", "Olympiad-style short-answer."),
    Anchor("arc_agi", "ARC-AGI (style)", "reasoning", "Apache-2.0", "low", "accuracy",
           "accuracy/100", "github:fchollet/ARC-AGI", "Abstraction & reasoning grids."),
    Anchor("gaia", "GAIA", "agentic_autonomy", "see-source", "medium", "accuracy",
           "accuracy/100", "hf:gaia-benchmark/GAIA", "Tool-using assistant tasks."),
    Anchor("tau_bench", "tau-bench", "agentic_autonomy", "MIT", "low", "pass^k",
           "pass_at_1", "github:sierra-research/tau-bench", "Policy-bound conversations."),
    Anchor("browsecomp", "BrowseComp (style)", "agentic_autonomy", "see-source",
           "low", "accuracy", "accuracy/100", "see-source", "Hard browsing tasks."),
    Anchor("webarena", "WebArena", "agentic_autonomy", "Apache-2.0", "medium",
           "success_rate", "success/100", "github:web-arena-x/webarena", "Web tasks."),
    Anchor("mmmu", "MMMU", "multimodal", "Apache-2.0", "medium", "accuracy",
           "accuracy/100", "hf:MMMU/MMMU", "College-level multimodal."),
    Anchor("mathvista", "MathVista", "multimodal", "CC-BY-SA-4.0", "medium", "accuracy",
           "accuracy/100", "hf:AI4Math/MathVista", "Visual math."),
    Anchor("chartqa", "ChartQA", "multimodal", "GPL-3.0", "high", "accuracy",
           "accuracy/100", "hf:HuggingFaceM4/ChartQA", "Chart understanding."),
    Anchor("docvqa", "DocVQA", "multimodal", "see-source", "high", "anls", "anls",
           "hf:lmms-lab/DocVQA", "Document VQA."),
    Anchor("truthfulqa", "TruthfulQA", "truthfulness", "Apache-2.0", "high", "mc2",
           "mc2", "hf:truthfulqa/truthful_qa", "Imitative falsehoods."),
    Anchor("bbh", "BIG-Bench Hard", "reasoning", "Apache-2.0", "high", "accuracy",
           "accuracy/100", "hf:lukaemon/bbh", "Hard BIG-Bench subset."),
    Anchor("drop", "DROP", "reasoning", "CC-BY-SA-4.0", "high", "f1", "f1/100",
           "hf:ucinlp/drop", "Discrete reasoning over paragraphs."),
    Anchor("hotpotqa", "HotpotQA", "memory", "CC-BY-SA-4.0", "high", "f1", "f1/100",
           "hf:hotpotqa/hotpot_qa", "Multi-hop QA."),
    Anchor("healthbench", "HealthBench (style)", "science", "see-source", "low",
           "rubric", "rubric", "see-source", "Rubric-scored medical (medical_safe only)."),
]}


def list_anchors(dimension: str | None = None) -> list[Anchor]:
    out = list(ANCHORS.values())
    if dimension:
        out = [a for a in out if a.dimension == dimension]
    return sorted(out, key=lambda a: (a.dimension, a.key))


def normalize_score(anchor_key: str, native_value: float) -> float:
    """Map a native anchor metric onto a 0..1 capability fraction."""
    a = ANCHORS[anchor_key]
    rule = a.normalize
    if rule.endswith("/100"):
        return max(0.0, min(1.0, native_value / 100.0))
    # pass_at_1 / mc2 / anls / f1 / success etc. assumed already 0..1 (or 0..100)
    return max(0.0, min(1.0, native_value / 100.0 if native_value > 1.0 else native_value))


def contamination_summary() -> dict:
    risk = {"low": 0, "medium": 0, "high": 0}
    for a in ANCHORS.values():
        risk[a.contamination_risk] = risk.get(a.contamination_risk, 0) + 1
    return {"total_anchors": len(ANCHORS), "by_contamination_risk": risk,
            "note": "high-risk anchors are likely in training data; use for calibration "
                    "context only, never as evidence of capability."}
