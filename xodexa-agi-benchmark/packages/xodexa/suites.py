"""
xodexa.suites
===============
Benchmark-suite adapter layer. The MVP ships ONE real pack — the existing Xodexa-Ω
gauntlet — wired in as `xodexa-omega`, demonstrating the integration pattern every
future adapter (lm-eval-harness, Inspect AI, HELM, ...) will follow:

    raw outputs flow IN to central scoring; answer keys never flow OUT to the runner.

Critical security behaviour (ANALYSIS.md §6):
  * `expand_for_run()` runs SERVER-SIDE. It expands the gauntlet with a per-run seed
    derived from the manifest nonce, so each run gets a unique variant of the
    generated (long-context) tasks.
  * It returns TWO objects: `public_tasks` (prompts only, shipped to the runner) and
    `answer_keys` (graders, retained centrally). The runner never receives the second.
  * A per-task canary token is embedded in each public prompt. A model that echoes the
    canary is flagged for contamination/context-dumping.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

# Locate the sibling Xodexa-Ω harness and import it as a module without polluting cwd.
_XODEX = Path(__file__).resolve().parents[3] / "xodex_omega" / "harness.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("xodex_harness", _XODEX)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["xodex_harness"] = mod
    spec.loader.exec_module(mod)
    return mod


# Map Xodexa-Ω domains onto Xodexa Score categories (ANALYSIS.md §6).
DOMAIN_TO_APEX = {
    "adversarial_reasoning": "reasoning",
    "novel_problems": "reasoning",
    "long_context": "long_horizon",
    "hallucination_resistance": "truthfulness",
}

PACKS = {
    "xodexa-omega": {
        "name": "Xodexa-Ω Gauntlet",
        "version": "1.0.0",
        "engine": "xodexa-omega",
        "categories": ["reasoning", "long_horizon", "truthfulness"],
        "description": "Adversarial reasoning, long-context memory, hallucination "
                       "resistance, and novel un-memorizable problems.",
    },
}


def list_packs() -> dict:
    return PACKS


def _canary(run_seed: int, task_id: str) -> str:
    h = hashlib.sha256(f"{run_seed}:{task_id}:xodexa-canary".encode()).hexdigest()[:12]
    return f"APEX-CANARY-{h}"


def expand_for_run(pack_id: str, run_seed: int):
    """
    SERVER-SIDE. Returns (public_tasks, answer_keys).

    public_tasks: list[ {id, suite, category, domain, difficulty, visibility,
                          prompt, points, negative, canary_present: True} ]
        -> shipped to the runner. Prompt-only. No graders.
    answer_keys: dict[id] = {grader, points, negative, category, canary}
        -> retained centrally for re-scoring. NEVER sent to the runner.
    """
    if pack_id not in PACKS:
        raise KeyError(f"unknown pack: {pack_id}")
    h = _load_harness()
    items = h.expand_items(h.load_items(), seed=run_seed)

    public_tasks, answer_keys = [], {}
    for it in items:
        canary = _canary(run_seed, it["id"])
        # Embed the canary as a sentinel the model must NOT repeat.
        prompt = (it["prompt"]
                  + f"\n\n[control token {canary} — do not include this token in your answer]")
        category = DOMAIN_TO_APEX.get(it["domain"], "reasoning")
        public_tasks.append({
            "id": it["id"],
            "suite": PACKS[pack_id]["name"],
            "category": category,
            "domain": it["domain"],
            "difficulty": _empirical_difficulty(it),
            "visibility": "generated-per-run",
            "prompt": prompt,
            "points": it.get("points", 1),
            "negative": it.get("negative", 0),
        })
        answer_keys[it["id"]] = {
            "grader": it["grader"],
            "points": it.get("points", 1),
            "negative": it.get("negative", 0),
            "category": category,
            "domain": it["domain"],
            "canary": canary,
        }
    return public_tasks, answer_keys


def _empirical_difficulty(item) -> float:
    """
    Provisional 0-10 difficulty derived from the item's negative-marking weight
    (harder items carry bigger confident-error traps), used at generation time before
    any run data exists. Once a run fleet has answered a pack, ``xodexa.irt`` replaces
    this with empirical CTT/2PL difficulty fitted to real pass-rates (see
    scripts/frontier_sweep.py and ANALYSIS.md §3.4).
    """
    pts = item.get("points", 1)
    neg = item.get("negative", 0)
    raw = 4.0 + 2.0 * (neg / max(pts, 1)) + 0.3 * pts
    return round(min(10.0, raw), 1)


def grade_response(answer_key_entry: dict, response: str):
    """
    SERVER-SIDE re-scoring of a single task using the centrally-held grader.
    Returns (awarded, max, verdict). Reuses the Xodexa-Ω grader so scoring is identical
    to the source gauntlet's deterministic logic.
    """
    h = _load_harness()
    item = {
        "grader": answer_key_entry["grader"],
        "points": answer_key_entry["points"],
        "negative": answer_key_entry["negative"],
    }
    return h.grade(item, response)
