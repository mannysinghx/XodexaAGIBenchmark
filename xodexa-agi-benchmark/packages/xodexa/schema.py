"""
xodexa.schema
===============
The strict task schema every Xodexa task conforms to, implemented with stdlib
dataclasses (no pydantic dependency in the core, so the engine stays importable in
air-gapped runners). Mirrors the spec's JSON schema field-for-field.

The two security-critical invariants the schema enforces:

  * ``expected_answer`` is populated ONLY for public/validation tasks. For
    ``private_hidden`` and ``dynamic`` tasks it MUST be ``None`` in any object that
    could be shipped to a runner — the answer key lives server-side (see
    ``contamination_controls.release_status`` and ``hidden_tests``).
  * Every task carries ``contamination_controls`` (canary, source hash, generation
    time, release status) so the contamination subsystem can act on it.

Use :func:`new_task` to build tasks (fills sane defaults + computes derived fields),
:func:`validate_task` to check one, and :func:`public_view` to strip answer keys
before a task ever leaves the trust boundary.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

from . import families
from .crypto import sha256_hex

TASK_FAMILIES = set(families.FAMILY_KEYS)
VISIBILITY = {"public", "validation", "private_hidden", "dynamic"}
MODALITIES = {"text", "image", "audio", "video", "code", "tool_use"}
ANSWER_TYPES = {"exact", "numeric", "code_patch", "rubric", "final_state", "proof",
                "structured_json"}
RELEASE_STATUS = {"public", "validation", "private", "rotated", "retired"}

DEFAULT_RUBRIC = {
    "correctness": 0.40, "reasoning": 0.15, "robustness": 0.15,
    "calibration": 0.10, "efficiency": 0.10, "safety": 0.10,
}


@dataclass
class ContaminationControls:
    canary: str = ""
    generated_at: str = ""
    source_hash: str = ""
    public_similarity_score: float = 0.0
    release_status: str = "private"


@dataclass
class HumanBaseline:
    average_human_score: float | None = None
    expert_human_score: float | None = None
    median_human_time_minutes: float | None = None
    error_rate: float | None = None
    inter_rater_agreement: float | None = None


@dataclass
class Provenance:
    created_by: str = "generator"          # generator | human_expert | hybrid
    review_status: str = "unreviewed"      # unreviewed | reviewed | expert_verified
    reviewer_count: int = 0
    license: str = "Xodexa-private"


@dataclass
class SafetyNotes:
    risk_domain: str = "none"  # none|cyber_safe|bio_safe|medical_safe|legal_safe|finance_safe
    harmful_content_removed: bool = True


@dataclass
class Task:
    task_id: str
    task_family: str
    subdomain: str
    prompt: str
    expected_answer_type: str
    difficulty: float = 5.0
    difficulty_band: str = ""
    visibility: str = "public"
    modality: list[str] = field(default_factory=lambda: ["text"])
    requires_tools: bool = False
    tools_allowed: list[str] = field(default_factory=list)
    input_assets: list[dict] = field(default_factory=list)
    # Public answer key (public/validation only). server_grader is the deterministic
    # grader spec re-used by the Ω-style central grader; it is NEVER in a public_view.
    expected_answer: Any = None
    server_grader: dict | None = None
    hidden_tests: str = "server_side_only"
    scoring_rubric: dict = field(default_factory=lambda: dict(DEFAULT_RUBRIC))
    human_baseline: HumanBaseline = field(default_factory=HumanBaseline)
    contamination_controls: ContaminationControls = field(default_factory=ContaminationControls)
    provenance: Provenance = field(default_factory=Provenance)
    safety_notes: SafetyNotes = field(default_factory=SafetyNotes)
    # bookkeeping
    points: float = 1.0
    negative: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def new_task(task_id: str, task_family: str, subdomain: str, prompt: str,
             expected_answer_type: str, *, server_grader: dict | None = None,
             expected_answer: Any = None, difficulty: float = 5.0,
             visibility: str = "public", modality: list[str] | None = None,
             requires_tools: bool = False, tools_allowed: list[str] | None = None,
             input_assets: list[dict] | None = None, points: float = 1.0,
             negative: float = 0.0, created_by: str = "generator",
             license: str = "Xodexa-private", risk_domain: str = "none",
             canary: str = "", generated_at: str | None = None) -> Task:
    """Construct a Task, computing derived fields (difficulty_band, source_hash,
    release_status) and enforcing the public-answer invariant."""
    modality = modality or ["text"]
    generated_at = generated_at or _iso(time.time())
    release = {"public": "public", "validation": "validation"}.get(visibility, "private")

    # Enforce: hidden/dynamic tasks must not carry a public answer.
    if visibility in ("private_hidden", "dynamic"):
        expected_answer = None

    src = sha256_hex({"f": task_family, "s": subdomain, "p": prompt,
                      "g": server_grader})
    t = Task(
        task_id=task_id, task_family=task_family, subdomain=subdomain, prompt=prompt,
        expected_answer_type=expected_answer_type, difficulty=round(difficulty, 2),
        difficulty_band=families.difficulty_band(difficulty), visibility=visibility,
        modality=modality, requires_tools=requires_tools,
        tools_allowed=tools_allowed or [], input_assets=input_assets or [],
        expected_answer=expected_answer, server_grader=server_grader, points=points,
        negative=negative,
        contamination_controls=ContaminationControls(
            canary=canary, generated_at=generated_at, source_hash=src,
            release_status=release),
        provenance=Provenance(created_by=created_by, license=license),
        safety_notes=SafetyNotes(risk_domain=risk_domain, harmful_content_removed=True),
    )
    return t


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def validate_task(t: Task | dict) -> list[str]:
    """Return a list of validation errors ([] == valid)."""
    d = t.to_dict() if isinstance(t, Task) else t
    errs: list[str] = []

    def req(cond, msg):
        if not cond:
            errs.append(msg)

    req(bool(d.get("task_id")), "task_id required")
    req(d.get("task_family") in TASK_FAMILIES,
        f"task_family must be one of {sorted(TASK_FAMILIES)}")
    req(bool(d.get("subdomain")), "subdomain required")
    req(bool(d.get("prompt")), "prompt required")
    req(d.get("expected_answer_type") in ANSWER_TYPES,
        f"expected_answer_type must be one of {sorted(ANSWER_TYPES)}")
    req(d.get("visibility") in VISIBILITY,
        f"visibility must be one of {sorted(VISIBILITY)}")
    diff = d.get("difficulty", -1)
    req(isinstance(diff, (int, float)) and 0 <= diff <= 10, "difficulty must be 0..10")
    pts = d.get("points", 1.0)
    neg = d.get("negative", 0.0)
    req(isinstance(pts, (int, float)) and pts > 0, "points must be > 0")
    # negative > points would let one confidently-wrong item wipe out more credit than
    # the item is worth, driving category scores toward -inf.
    req(isinstance(neg, (int, float)) and 0 <= neg <= pts,
        "negative must be in [0, points]")
    mods = d.get("modality") or []
    req(isinstance(mods, list) and set(mods) <= MODALITIES,
        f"modality must be a subset of {sorted(MODALITIES)}")
    rub = d.get("scoring_rubric") or {}
    if rub:
        req(abs(sum(rub.values()) - 1.0) < 1e-6, "scoring_rubric weights must sum to 1.0")
    cc = d.get("contamination_controls") or {}
    req(cc.get("release_status") in RELEASE_STATUS,
        f"release_status must be one of {sorted(RELEASE_STATUS)}")
    # The critical invariant: no public answer on hidden/dynamic tasks.
    if d.get("visibility") in ("private_hidden", "dynamic"):
        req(d.get("expected_answer") is None,
            "private_hidden/dynamic tasks must not carry expected_answer")
    if d.get("requires_tools"):
        req("tool_use" in mods or bool(d.get("tools_allowed")),
            "requires_tools set but no tools_allowed / tool_use modality")
    return errs


def is_valid(t: Task | dict) -> bool:
    return not validate_task(t)


# --------------------------------------------------------------------------- #
# Trust-boundary views
# --------------------------------------------------------------------------- #

# Fields that constitute the answer key and MUST be stripped before a task is shown
# to an untrusted runner (any visibility, in official mode).
_ANSWER_KEY_FIELDS = ("expected_answer", "server_grader", "hidden_tests")


def public_view(t: Task | dict) -> dict:
    """Strip the answer key. Use this for ANY task shipped to a runner in official
    mode, and for hidden/dynamic tasks always. The canary stays (we want to detect
    echoes), the grader/answer go."""
    d = t.to_dict() if isinstance(t, Task) else dict(t)
    for f in _ANSWER_KEY_FIELDS:
        d.pop(f, None)
    return d


def answer_key(t: Task | dict) -> dict:
    """Extract the server-side answer key for central re-scoring."""
    d = t.to_dict() if isinstance(t, Task) else dict(t)
    return {
        "task_id": d["task_id"],
        "category": families.FAMILY_TO_DIMENSION.get(d["task_family"], "reasoning"),
        "family": d["task_family"],
        "subdomain": d.get("subdomain", ""),
        "difficulty": d.get("difficulty", 5.0),
        "grader": d.get("server_grader"),
        "expected_answer": d.get("expected_answer"),
        "points": d.get("points", 1.0),
        "negative": d.get("negative", 0.0),
        "canary": (d.get("contamination_controls") or {}).get("canary", ""),
    }
