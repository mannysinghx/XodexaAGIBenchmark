"""Xodexa AGI Benchmark — core trust kernel (crypto, scoring, suites, authority, runner)."""
from .crypto import KeyPair, HashChain, verify, sha256_hex, canonical, fingerprint
from .authority import ScoringAuthority, BENCHMARK_VERSION
from .runner import RunnerAgent, CallableConnector, OpenAICompatibleConnector, OllamaConnector
from .calibration import (accuracy, wilson_ci, rms_calibration_error, rank_upper_bound)
from . import scoring, suites, calibration

__all__ = [
    "KeyPair", "HashChain", "verify", "sha256_hex", "canonical", "fingerprint",
    "ScoringAuthority", "BENCHMARK_VERSION", "RunnerAgent", "CallableConnector",
    "OpenAICompatibleConnector", "OllamaConnector", "scoring", "suites", "calibration",
    "accuracy", "wilson_ci", "rms_calibration_error", "rank_upper_bound",
]
