#!/usr/bin/env python3
"""
build_seed.py — generate the Xodexa AI Benchmark MVP seed corpus.

Produces, under ``datasets/`` (and server-side answer keys under ``server_keys/``,
which is git-ignored to embody the trust boundary):

  Layer 1  Xodexa Public Validation Set      — 1,000 tasks (public answers shipped)
  Layer 2  Xodexa Private Hidden Official Set — 500 tasks (PUBLIC VIEWS only shipped;
                                                answer keys go to server_keys/)
  Layer 3  Dynamic Runtime-Generated Set      — generator catalog + 100 sample variants
  Focused packs                               — agent(50), code(50), multimodal(50),
                                                safety(25), truthfulness(25)
  Family "Mini" packs                         — one per family (the building blocks)

Every shippable release gets a signed, checksummed manifest via the generation
pipeline (generate -> difficulty -> contamination -> quality -> calibration -> sign).

This is the MVP scale; the same code scales to 1M public / 100k hidden by raising the
counts — generation, filtering and signing are all O(n) and seed-reproducible.

    python scripts/build_seed.py            # build everything
    python scripts/build_seed.py --quick    # tiny build for CI smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))  # beat any shadow 'xodexa' on site-packages

from xodexa import generators as G  # noqa: E402
from xodexa import families, schema  # noqa: E402
from xodexa.contamination import CorpusIndex  # noqa: E402
from xodexa.crypto import KeyPair  # noqa: E402
from xodexa.pipeline import DatasetPipeline  # noqa: E402

DATASETS = ROOT / "datasets"
SERVER_KEYS = ROOT / "server_keys"


def _write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _family_allocation(total: int) -> dict[str, int]:
    """Distribute `total` tasks across families, weighted by scoring weight, min 25."""
    weights = {fam: families.SCORE_WEIGHTS.get(families.FAMILY_TO_DIMENSION[fam], 0.04)
               for fam in families.FAMILY_KEYS}
    wsum = sum(weights.values())
    alloc = {fam: max(25, round(total * w / wsum)) for fam, w in weights.items()}
    # adjust to hit `total` exactly
    diff = total - sum(alloc.values())
    keys = list(alloc)
    i = 0
    while diff != 0:
        k = keys[i % len(keys)]
        if diff > 0:
            alloc[k] += 1; diff -= 1
        elif alloc[k] > 25:
            alloc[k] -= 1; diff += 1
        i += 1
        if i > 100000:
            break
    return alloc


def build_pack(name, version, family_counts, *, visibility, seed, signer, corpus,
              ship_keys_publicly: bool):
    """Generate a pack across families, run the pipeline, write outputs.
    Returns the manifest summary dict."""
    tasks = []
    for fam, n in family_counts.items():
        tasks += G.generate(family=fam, n=n, seed=seed + hash(fam) % 9973,
                            visibility=visibility)
    rel = DatasetPipeline(corpus=corpus, signer=signer).run(
        tasks, name, version, changelog=f"MVP seed build of {name}")

    slug = name.lower().replace(" ", "-").replace("/", "-")
    out_dir = DATASETS / slug
    _write_jsonl(out_dir / "tasks_public_view.jsonl", rel.public_tasks)
    _write_json(out_dir / "manifest.json", rel.manifest)
    _write_json(out_dir / "manifest.sig", {"signature": rel.signature,
                                           "signer_pub": rel.manifest["signer_pub"]})
    _write_json(out_dir / "rejected.json", rel.rejected)

    # Answer keys: public/validation are public; hidden go to server_keys/ (git-ignored).
    keys_dir = out_dir if ship_keys_publicly else SERVER_KEYS
    _write_json(keys_dir / f"{slug}.answer_keys.json", rel.answer_keys)

    return {"name": name, "version": version, "slug": slug,
            "task_count": rel.manifest["task_count"],
            "checksum": rel.manifest["checksum_sha256"],
            "visibility": visibility,
            "keys_location": "public" if ship_keys_publicly else "server_keys (git-ignored)",
            "families": rel.manifest["families"],
            "difficulty_bands": rel.manifest["difficulty"]["bands"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="tiny build for CI")
    args = ap.parse_args()

    signer = KeyPair.generate()
    corpus = CorpusIndex()  # in a real build, preload with public-benchmark/web snippets
    scale = 0.05 if args.quick else 1.0

    def s(n):
        return max(2, round(n * scale))

    summary = {"benchmark_version": "1.0.0", "scale": scale,
               "signer_pub": signer.pub_b64, "releases": []}

    # --- Layer 1: Public Validation Set (1,000) ---
    pub_alloc = _family_allocation(s(1000))
    summary["releases"].append(build_pack(
        "Xodexa Public Validation", "1.0.0", pub_alloc, visibility="public",
        seed=1001, signer=signer, corpus=corpus, ship_keys_publicly=True))

    # --- Layer 2: Private Hidden Official Set (500) ---
    hid_alloc = _family_allocation(s(500))
    summary["releases"].append(build_pack(
        "Xodexa Hidden Official", "1.0.0", hid_alloc, visibility="private_hidden",
        seed=5005, signer=signer, corpus=corpus, ship_keys_publicly=False))

    # --- Layer 3: Dynamic generators (catalog + 100 sample variants) ---
    catalog = [{"generator_id": gs.generator_id, "family": gs.family,
                "blurb": (gs.blurb or "").strip().split("\n")[0][:160]}
               for gs in G.list_generators()]
    dyn_tasks = G.generate(n=s(100), seed=9009, visibility="dynamic")
    dyn_views = [schema.public_view(t) for t in dyn_tasks]
    _write_json(DATASETS / "dynamic" / "generator_catalog.json",
                {"generator_count": len(catalog),
                 "note": "Each generator yields unlimited seed-reproducible variants; "
                         "answers are minted server-side per run and never shipped.",
                 "generators": catalog})
    _write_jsonl(DATASETS / "dynamic" / "sample_variants_public_view.jsonl", dyn_views)
    summary["dynamic"] = {"generator_count": len(catalog),
                          "sample_variants": len(dyn_views)}

    # --- Focused demonstration packs ---
    focused = [("Xodexa Agent Mini", {"agent": s(50)}),
               ("Xodexa Code Mini", {"code": s(50)}),
               ("Xodexa Multimodal Mini", {"multimodal": s(50)}),
               ("Xodexa Safety Mini", {"safety": s(25)}),
               ("Xodexa Truthfulness Mini", {"truthfulness": s(25)})]
    summary["focused_packs"] = []
    for nm, counts in focused:
        summary["focused_packs"].append(build_pack(
            nm, "1.0.0", counts, visibility="validation", seed=7007 + len(nm),
            signer=signer, corpus=corpus, ship_keys_publicly=True))

    # --- Per-family Mini packs (the building blocks; small) ---
    summary["family_minis"] = []
    for fam in families.FAMILY_KEYS:
        summary["family_minis"].append(build_pack(
            f"Xodexa {families.FAMILIES[fam].title}", "1.0.0", {fam: s(40)},
            visibility="validation", seed=3003 + len(fam), signer=signer,
            corpus=corpus, ship_keys_publicly=True))

    _write_json(DATASETS / "SUMMARY.json", summary)

    # console report
    print("=" * 70)
    print("  Xodexa AI Benchmark — seed corpus built")
    print("=" * 70)
    for r in summary["releases"]:
        print(f"  {r['name']:<32} {r['task_count']:>6} tasks  [{r['keys_location']}]")
    print(f"  {'Dynamic generators':<32} {summary['dynamic']['generator_count']:>6} "
          f"generators (+{summary['dynamic']['sample_variants']} sample variants)")
    print("  Focused packs : " + ", ".join(
        f"{p['name'].split()[1]}({p['task_count']})" for p in summary["focused_packs"]))
    print(f"  Family minis  : {len(summary['family_minis'])} packs")
    total = (sum(r["task_count"] for r in summary["releases"])
             + sum(p["task_count"] for p in summary["focused_packs"])
             + sum(p["task_count"] for p in summary["family_minis"])
             + summary["dynamic"]["sample_variants"])
    print(f"  TOTAL TASKS   : {total}")
    print(f"  Output        : {DATASETS}")
    print(f"  Hidden keys   : {SERVER_KEYS} (git-ignored — never shipped)")
    print("=" * 70)


if __name__ == "__main__":
    main()
