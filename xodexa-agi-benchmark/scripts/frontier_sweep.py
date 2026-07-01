#!/usr/bin/env python3
"""
frontier_sweep.py — run the benchmark against a fleet of real models and turn the
results into (a) the first real leaderboard, (b) EMPIRICAL item difficulty (IRT),
and (c) pairwise significance with FDR control.

This is the harness that makes the benchmark *exist*: a benchmark nobody has run
against real frontier models is a spec, not a benchmark. It doubles as the battle
test for the connectors (which otherwise have no real-call coverage) and as the data
source that replaces hand-assigned difficulty (xodexa.irt).

Models are described in a JSON config (see --config); each entry:
    {"name": "gpt-x", "connector": "openai-compatible:https://.../v1:model-id",
     "api_key_env": "OPENAI_API_KEY"}
The 'callable:PERSONA' connector spec (accuracy simulation) lets the whole pipeline
be exercised offline / in CI without spending tokens — that is the default config.

    python scripts/frontier_sweep.py --family reasoning --n 40 --out results/sweep.json
    python scripts/frontier_sweep.py --config models.json --n 60 --seed 7
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from xodexa import generators as G, schema  # noqa: E402
from xodexa.grade import grade  # noqa: E402
from xodexa.irt import ctt_statistics, fit_2pl, flag_bad_items  # noqa: E402
from xodexa.runner import (CallableConnector, OpenAICompatibleConnector,  # noqa: E402
                           AnthropicConnector, OllamaConnector)
from xodexa.stats import pairwise_significance, min_n_gate  # noqa: E402

# Offline default fleet — deterministic accuracy personas (no API calls). Each 'skill'
# is the probability a persona answers a task correctly; the sweep is fully reproducible.
_DEFAULT_FLEET = [
    {"name": "sim-frontier", "connector": "sim:0.82"},
    {"name": "sim-strong", "connector": "sim:0.68"},
    {"name": "sim-mid", "connector": "sim:0.50"},
    {"name": "sim-weak", "connector": "sim:0.32"},
]


def _sim_connector(skill: float, name: str):
    """A persona that 'knows' each task with probability `skill`, deterministically
    per (task prompt) so re-runs match. Emits the oracle answer when it 'knows' it,
    else a plausible wrong answer."""
    import hashlib

    def fn(prompt: str) -> str:
        # Deterministic pseudo-random draw from the prompt.
        h = int(hashlib.sha256((name + prompt).encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        knows = h < skill
        # The sweep passes (prompt -> oracle answer) via a side table; see run_model.
        return "__KNOWS__" if knows else "__MISSES__"

    return CallableConnector(fn, name=name)


def build_connector(spec: str, api_key: str | None):
    if spec.startswith("sim:"):
        return _sim_connector(float(spec.split(":", 1)[1]), spec)
    if spec.startswith("openai-compatible:"):
        _, base, model = spec.split(":", 2)
        return OpenAICompatibleConnector(base, model, api_key or "not-needed")
    if spec.startswith("anthropic:"):
        model = spec.split(":", 1)[1]
        return AnthropicConnector(api_key or "", model)
    if spec.startswith("ollama:"):
        _, base, model = spec.split(":", 2)
        return OllamaConnector(base, model)
    raise SystemExit(f"unknown connector spec: {spec}")


def run_model(entry: dict, tasks, keys) -> dict:
    """Return {name, correct: {task_id: 0/1}, scored, accuracy}."""
    api_key = os.environ.get(entry.get("api_key_env", ""), "") or entry.get("api_key")
    conn = build_connector(entry["connector"], api_key)
    is_sim = entry["connector"].startswith("sim:")
    correct: dict[str, int] = {}
    for t in tasks:
        key = keys[t.task_id]
        if is_sim:
            # Oracle-vs-miss simulation keeps the pipeline honest without tokens.
            from xodexa.grade import synth_good, synth_bad
            verdict = conn.complete(t.prompt)
            answer = synth_good(key["grader"]) if verdict == "__KNOWS__" \
                else synth_bad(key["grader"])
        else:
            answer = conn.complete(t.prompt)
        aw, mx, _ = grade(key["grader"], answer, key.get("points", 1),
                          key.get("negative", 0))
        correct[t.task_id] = 1 if (mx and aw >= 0.5 * mx) else 0
    acc = sum(correct.values()) / len(correct) if correct else 0.0
    return {"name": entry["name"], "correct": correct,
            "n": len(correct), "accuracy": round(acc, 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Frontier baseline sweep + IRT calibration.")
    ap.add_argument("--config", help="JSON file: list of model entries")
    ap.add_argument("--family", default="reasoning")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    fleet = json.loads(Path(args.config).read_text()) if args.config else _DEFAULT_FLEET

    # ONE fixed-seed pack so every model sees identical items — the prerequisite for
    # paired significance testing and IRT.
    tasks = G.generate(family=args.family, n=args.n, seed=args.seed,
                       visibility="validation")
    keys = {t.task_id: schema.answer_key(t) for t in tasks}
    print(f"Sweep: {len(fleet)} models × {len(tasks)} {args.family} tasks "
          f"(seed {args.seed})")

    results = [run_model(e, tasks, keys) for e in fleet]
    for r in results:
        print(f"  {r['name']:>16}: accuracy {r['accuracy']:.3f}")

    matrix = {r["name"]: r["correct"] for r in results}

    ctt = ctt_statistics(matrix)
    irt = fit_2pl(matrix)
    quality = flag_bad_items(ctt)
    sig = pairwise_significance({n: [c[t.task_id] for t in tasks]
                                 for n, c in matrix.items()})

    report = {
        "family": args.family, "seed": args.seed, "n_items": len(tasks),
        "generated_at": int(time.time()),
        "leaderboard": sorted(
            [{"model": r["name"], "accuracy": r["accuracy"], "n": r["n"],
              "ability_theta": irt.ability.get(r["name"]),
              **min_n_gate(r["n"])} for r in results],
            key=lambda x: -x["accuracy"]),
        "item_difficulty": {
            it: {"empirical_ctt": ctt[it]["difficulty_0_10"],
                 "irt_2pl": irt.difficulty_0_10.get(it),
                 "discrimination": ctt[it]["discrimination"],
                 "pass_rate": ctt[it]["pass_rate"]}
            for it in ctt},
        "item_quality": {"keep": len(quality["keep"]), "drop": quality["drop"]},
        "pairwise_significance": sig,
        "irt_degenerate_items": irt.degenerate_items,
    }

    out = args.out or f"results/sweep_{args.family}_{args.seed}.json"
    out_path = ROOT / out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")
    print(f"  kept {len(quality['keep'])} items, flagged {len(quality['drop'])} "
          f"(too easy / non-discriminating)")
    print(f"  {sum(1 for s in sig if s['significant'])}/{len(sig)} model pairs "
          f"significantly different after FDR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
