#!/usr/bin/env python3
"""
rotate_hidden_set.py — regenerate the private hidden official set on a fresh seed.

The platform's whole contamination story depends on the hidden set being a MOVING
target: once a set has been used against enough models, its items risk leaking into
training data. This script institutionalizes rotation — the architecture already
supports it (seeded generators + server-side keys), this makes it a one-command,
versioned, auditable operation.

What it does:
  1. Reads the current hidden-set version from server_keys/rotation_log.json
     (or starts at v1 if absent).
  2. Regenerates the hidden pack from the SAME family composition but a NEW rotation
     seed derived from (base_seed, new_version) — so every rotation is reproducible
     from the log yet disjoint from prior rotations.
  3. Writes fresh public views to datasets/xodexa-hidden-official/ and fresh answer
     keys to server_keys/ (git-ignored), signed + checksummed via the pipeline.
  4. Appends a rotation record (version, seed, checksum, timestamp, task_count) to
     server_keys/rotation_log.json and marks the prior version 'retired'.

Retired sets can be published (their keys moved from server_keys/ to datasets/) so the
community can study them — a healthy benchmark ages its hidden items into public ones.

    python scripts/rotate_hidden_set.py                 # rotate to next version
    python scripts/rotate_hidden_set.py --dry-run       # show what would change
    python scripts/rotate_hidden_set.py --timestamp 1751... # deterministic ts for CI
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from xodexa import generators as G  # noqa: E402
from xodexa.contamination import CorpusIndex  # noqa: E402
from xodexa.crypto import KeyPair, sha256_hex  # noqa: E402
from xodexa.pipeline import DatasetPipeline  # noqa: E402

DATASETS = ROOT / "datasets"
SERVER_KEYS = ROOT / "server_keys"
ROTATION_LOG = SERVER_KEYS / "rotation_log.json"
HIDDEN_SLUG = "xodexa-hidden-official"

# Same composition the seed build uses for the hidden official set (all 21 families).
HIDDEN_COMPOSITION: dict[str, int] = {
    "reasoning": 30, "math": 30, "science": 25, "code": 30, "agent": 30,
    "multimodal": 20, "truthfulness": 25, "memory": 20, "strategy": 15,
    "creativity": 15, "meta_learning": 15, "instruction_following": 15,
    "safety": 20, "jailbreak_resistance": 25, "tool_safety": 20,
    "privacy_security": 15, "agentic_safety": 15, "over_refusal": 15,
    "rag_poisoning": 15, "multi_turn_manipulation": 10, "high_stakes_safety": 10,
    "canary_resistance": 10,
}

BASE_SEED = 5005  # matches build_seed.py's hidden-set seed lineage


def load_log() -> dict:
    if ROTATION_LOG.exists():
        return json.loads(ROTATION_LOG.read_text())
    return {"current_version": 0, "rotations": []}


def rotation_seed(version: int) -> int:
    """Deterministic, disjoint-per-version seed derived from the base lineage."""
    return int(sha256_hex(f"hidden-rotation:{BASE_SEED}:v{version}".encode())[:12], 16)


def build_hidden(version: int, seed: int, signer: KeyPair, scale: float) -> dict:
    corpus = CorpusIndex()
    tasks = []
    for fam, n in HIDDEN_COMPOSITION.items():
        count = max(1, int(n * scale))
        tasks += G.generate(family=fam, n=count,
                            seed=seed + hash(fam) % 9973, visibility="private_hidden")
    rel = DatasetPipeline(corpus=corpus, signer=signer).run(
        tasks, "Xodexa Hidden Official", f"{version}.0.0",
        changelog=f"Hidden-set rotation v{version} (seed {seed})")
    return {"release": rel, "tasks": tasks}


def main() -> int:
    ap = argparse.ArgumentParser(description="Rotate the hidden official set.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scale", type=float, default=1.0, help="fraction of full size")
    ap.add_argument("--timestamp", type=int, default=None,
                    help="fixed unix ts for reproducible logs (default: now)")
    ap.add_argument("--publish-retired", action="store_true",
                    help="move the prior version's keys from server_keys/ to datasets/")
    args = ap.parse_args()

    log = load_log()
    new_version = log["current_version"] + 1
    seed = rotation_seed(new_version)
    ts = args.timestamp
    if ts is None:
        import time
        ts = int(time.time())

    print(f"Rotating hidden official set: v{log['current_version']} -> v{new_version}")
    print(f"  rotation seed: {seed}")

    signer = KeyPair.generate()
    built = build_hidden(new_version, seed, signer, args.scale)
    rel = built["release"]
    checksum = rel.manifest["checksum_sha256"]
    task_count = rel.manifest["task_count"]
    print(f"  generated {task_count} tasks, checksum {checksum[:16]}…")

    if args.dry_run:
        print("  [dry-run] no files written.")
        return 0

    SERVER_KEYS.mkdir(exist_ok=True)
    out_dir = DATASETS / HIDDEN_SLUG
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tasks_public_view.jsonl").write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in rel.public_tasks) + "\n")
    (out_dir / "manifest.json").write_text(json.dumps(rel.manifest, indent=2))
    (out_dir / "manifest.sig").write_text(json.dumps(
        {"signature": rel.signature, "signer_pub": rel.manifest["signer_pub"]}, indent=2))
    (SERVER_KEYS / f"{HIDDEN_SLUG}.v{new_version}.answer_keys.json").write_text(
        json.dumps(rel.answer_keys, indent=2))
    # Keep the un-versioned filename pointing at the live set for the authority.
    (SERVER_KEYS / f"{HIDDEN_SLUG}.answer_keys.json").write_text(
        json.dumps(rel.answer_keys, indent=2))

    for r in log["rotations"]:
        if r["status"] == "active":
            r["status"] = "retired"
            r["retired_at"] = ts
    log["rotations"].append({
        "version": new_version, "seed": seed, "checksum": checksum,
        "task_count": task_count, "created_at": ts, "status": "active",
    })
    log["current_version"] = new_version
    ROTATION_LOG.write_text(json.dumps(log, indent=2))
    print(f"  wrote public views -> {out_dir}")
    print(f"  wrote answer keys  -> {SERVER_KEYS} (git-ignored)")
    print(f"  rotation log updated: {ROTATION_LOG}")
    print(f"Done. Live hidden set is now v{new_version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
