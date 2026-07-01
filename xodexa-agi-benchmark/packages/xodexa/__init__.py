"""Xodexa AGI Benchmark — core engine.

Phase 0 trust kernel: crypto, scoring, suites, authority, runner, calibration.
Platform layer: schema, families, generators, grade, contamination, pipeline,
evaluate, failure_analysis, agi_readiness, improvement, report, registry, anchors.
"""
from .crypto import KeyPair, HashChain, verify, sha256_hex, canonical, fingerprint
from .authority import ScoringAuthority, BENCHMARK_VERSION
from .runner import (RunnerAgent, CallableConnector, OpenAICompatibleConnector,
                     OllamaConnector, AnthropicConnector)
from .calibration import (accuracy, wilson_ci, rms_calibration_error, rank_upper_bound)
from . import (scoring, suites, calibration, families, schema, grade, generators,
               contamination, pipeline, evaluate, failure_analysis, agi_readiness,
               improvement, report, registry, anchors,
               deterministic_checks, safety_scoring, grader_prompt, compat,
               audit, human_review, attestation)
from .schema import Task, new_task, validate_task, public_view, answer_key
from .pipeline import DatasetPipeline, PipelineConfig
from .contamination import CorpusIndex

__all__ = [
    "KeyPair", "HashChain", "verify", "sha256_hex", "canonical", "fingerprint",
    "ScoringAuthority", "BENCHMARK_VERSION", "RunnerAgent", "CallableConnector",
    "OpenAICompatibleConnector", "OllamaConnector", "AnthropicConnector",
    "scoring", "suites", "calibration",
    "accuracy", "wilson_ci", "rms_calibration_error", "rank_upper_bound",
    # platform layer
    "families", "schema", "grade", "generators", "contamination", "pipeline",
    "evaluate", "failure_analysis", "agi_readiness", "improvement", "report",
    "registry", "anchors", "Task", "new_task", "validate_task", "public_view",
    "answer_key", "DatasetPipeline", "PipelineConfig", "CorpusIndex",
    # security upgrade modules
    "deterministic_checks", "safety_scoring", "grader_prompt", "compat",
    "audit", "human_review", "attestation",
]
