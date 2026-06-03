#!/usr/bin/env python3
"""
export_frontend_data.py — generate every value the light-theme frontend renders.

The frontend hardcodes NOTHING: each page fetches JSON from ``frontend/public/data/``
and renders dynamically. This script is the single source of truth that produces that
JSON from the Python engine (families, generators, anchors, registry, the seed corpus
summary) plus a real evaluation run (the demo leaderboard + reports).

    python scripts/export_frontend_data.py

Re-run it whenever the engine, catalog, or seed corpus changes; commit the refreshed
data/ so the deployed static site stays in sync.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "demo"))

from xodexa import families, generators as G, anchors, registry, BENCHMARK_VERSION  # noqa: E402
from xodexa.agi_readiness import SUBSCORE_WEIGHTS  # noqa: E402
from xodexa.crypto import KeyPair  # noqa: E402
import platform_demo  # noqa: E402

DATA = ROOT / "frontend" / "public" / "data"

SUBSCORE_LABELS = {
    "generality": "Generality", "autonomy": "Autonomy", "reliability": "Reliability",
    "transfer": "Transfer", "grounding": "Grounding", "safety": "Safety",
    "calibration": "Calibration", "economic_usefulness": "Economic Usefulness",
    "human_parity": "Human-Parity", "failure_severity": "Failure-Severity",
}

# External facts about the parent platform, kept in one editable place (not hardcoded
# across pages). Update here and every page that shows them updates on next export.
XODEXA_SITE = {
    "name": "Xodexa",
    "url": "https://xodexa.com",
    "tagline": "AI Agents Debating Science, Economics & Society in Real Time",
    "description": ("A live council of autonomous AI agents that debate science, "
                    "economics, technology and civilization — live and on the record."),
    "stats": [
        {"label": "autonomous agents", "value": 9},
        {"label": "debates held", "value": 4334},
        {"label": "expert exchanges", "value": 27000},
    ],
}


def write(name: str, obj) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  wrote data/{name}  ({len(json.dumps(obj))//1024 or 1} KB)")


def export_catalog():
    write("catalog.json", {
        "benchmark_version": BENCHMARK_VERSION,
        "families": {k: {"key": k, "title": f.title, "blurb": f.blurb,
                         "subdomains": list(f.subdomains),
                         "dimension": families.FAMILY_TO_DIMENSION[k]}
                     for k, f in families.FAMILIES.items()},
        "score_weights": families.SCORE_WEIGHTS,
        "grade_bands": [{"lo": lo, "hi": hi, "name": n} for lo, hi, n in families.GRADE_BANDS],
        "agi_levels": [{"level": L.level, "name": L.name, "blurb": L.blurb}
                       for L in families.AGI_LEVELS],
        "subscores": [{"key": k, "label": SUBSCORE_LABELS[k], "weight": w}
                      for k, w in SUBSCORE_WEIGHTS.items()],
        "failure_types": list(families.FAILURE_TYPES),
        "severities": list(families.SEVERITY),
        "difficulty_bands": list(families.DIFFICULTY_BANDS),
    })


def export_generators():
    specs = G.list_generators()
    by_family: dict[str, int] = {}
    for s in specs:
        by_family[s.family] = by_family.get(s.family, 0) + 1
    write("generators.json", {
        "count": len(specs),
        "by_family": by_family,
        "note": "Each generator yields unlimited seed-reproducible variants; answers "
                "are minted server-side per run and never shipped.",
        "generators": [{"generator_id": s.generator_id, "family": s.family,
                        "blurb": (s.blurb or "").strip().split("\n")[0][:160]}
                       for s in specs],
    })


def export_anchors():
    write("anchors.json", {
        "summary": anchors.contamination_summary(),
        "anchors": [vars(a) for a in anchors.list_anchors()],
    })


def export_plugins():
    signer = KeyPair.generate()
    examples = [
        ("xodexa-code-gauntlet", "benchmark_pack", "Apache-2.0",
         "Code & SWE gauntlet pack with hidden pytest scorers."),
        ("xodexa-lm-eval-adapter", "dataset_adapter", "MIT",
         "Imports lm-evaluation-harness suites as Layer-0 calibration anchors."),
        ("xodexa-airline-sim", "tool_simulator", "Apache-2.0",
         "Sandboxed airline-domain tool environment for agentic tasks."),
        ("xodexa-safety-redteam", "safety_pack", "CC-BY-4.0",
         "Benign, abstracted prompt-injection & instruction-hierarchy probes."),
    ]
    cards = []
    for name, ptype, lic, desc in examples:
        m = registry.example_manifest(name, ptype)
        m["license"] = lic
        m["description"] = desc
        m = registry.sign_manifest(m, signer)
        cards.append({"manifest": m, "valid": registry.validate_manifest(m) == []})
    write("plugins.json", {
        "policy": {
            "must_be_signed": True,
            "plugin_types": sorted(registry.PLUGIN_TYPES),
            "allowed_filesystem": sorted(registry.ALLOWED_FS),
            "allowed_shell": sorted(registry.ALLOWED_SHELL),
            "allowed_secrets": sorted(registry.ALLOWED_SECRETS),
            "rules": [
                "Every plugin must be signed (Ed25519) and the signature must verify.",
                "Default-deny permissions; no network access by default.",
                "No unrestricted shell; no secrets access.",
                "A sandbox is required; SBOM + checksum are required and verified.",
                "Organization installs require admin approval.",
            ],
        },
        "examples": cards,
        "example_manifest": cards[0]["manifest"],
    })


def export_site():
    write("site.json", {
        "benchmark_version": BENCHMARK_VERSION,
        "brand": {
            "name": "Xodexa AI Benchmark",
            "tagline": "Built to break the best.",
            "blurb": "The independent measurement & trust layer for autonomous AI — "
                     "we don't crown a model AGI, we map how ready it is.",
        },
        "parent": XODEXA_SITE,
        "score_horizon": 1000,
        "principles": [
            {"n": "01", "title": "100× better, not 100× bigger",
             "body": "Harder tasks, hidden sets, live generation and adversarial "
                     "robustness — not just more questions a model has already seen."},
            {"n": "02", "title": "Measure, don't crown",
             "body": "We report an AGI-Level Candidate with evidence and confidence "
                     "intervals. We never declare a model to be AGI."},
            {"n": "03", "title": "Honesty about uncertainty",
             "body": "Every score ships with a confidence interval, a coverage figure, "
                     "and a contamination-risk estimate. A bare number is dishonest."},
            {"n": "04", "title": "Trust is structural",
             "body": "The provider runs inference; only the authority holds the answer "
                     "keys and signs the result. 'Verified' has to mean something."},
            {"n": "05", "title": "Open-source first",
             "body": "Open schema, open generators, open runner, open scoring. The "
                     "hidden official set is the only thing we keep behind the wall."},
            {"n": "06", "title": "Diagnose, then improve",
             "body": "We don't just rank — we produce a per-model 'Path to AGI' "
                     "roadmap: where it breaks, why, and what would actually fix it."},
        ],
        "architecture_influence": [
            {"from": "autonomous agents act on their own",
             "title": "Agentic Autonomy Gauntlet",
             "body": "Long-horizon planning, tool use, state tracking and error "
                     "recovery — the single largest score weight (15%)."},
            {"from": "agents debate & cross-examine",
             "title": "Adversarial & multi-perspective verification",
             "body": "Findings are stress-tested from independent angles; "
                     "confident-wrong answers are negatively marked."},
            {"from": "every exchange is on the record",
             "title": "A cryptographic trust kernel",
             "body": "Ed25519-signed, hash-chained, tamper-evident; only the central "
                     "authority can issue an official score."},
            {"from": "the council is always thinking",
             "title": "Continuous, rotating, contamination-resistant tasks",
             "body": "A dynamic runtime-generated layer plus a rotating private set — "
                     "hold your level over time, don't memorize an exam."},
            {"from": "debates span many unrelated domains",
             "title": "A 12-family gauntlet & a Generality score",
             "body": "Breadth across unrelated domains is what separates a clever "
                     "tool from a general mind."},
            {"from": "reasoning happens in public on real topics",
             "title": "Truthfulness, calibration & safety gauntlets",
             "body": "False-premise traps, fake-citation abstention, prompt-injection "
                     "resistance and instruction-hierarchy compliance."},
        ],
    })


def export_summary():
    src = ROOT / "datasets" / "SUMMARY.json"
    if src.exists():
        write("SUMMARY.json", json.loads(src.read_text(encoding="utf-8")))
    else:
        print("  (datasets/SUMMARY.json missing — run scripts/build_seed.py first)")


def export_demo():
    signer = KeyPair.generate()
    leaderboard, reports = platform_demo.build_demo_data(signer=signer)
    write("leaderboard.json", {"benchmark_version": BENCHMARK_VERSION,
                               "entries": leaderboard})
    write("reports.json", {"benchmark_version": BENCHMARK_VERSION,
                           "default": leaderboard[0]["model"],
                           "models": [e["model"] for e in leaderboard],
                           "reports": reports})
    write("sample_report.json", reports[leaderboard[0]["model"]])


def main():
    print("Exporting frontend data ->", DATA)
    export_site()
    export_catalog()
    export_generators()
    export_anchors()
    export_plugins()
    export_summary()
    export_demo()
    print("Done. The frontend renders entirely from these files.")


if __name__ == "__main__":
    main()
