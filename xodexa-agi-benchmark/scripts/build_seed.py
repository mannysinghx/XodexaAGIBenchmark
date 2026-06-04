#!/usr/bin/env python3
"""
build_seed.py — generate the Xodexa AI Benchmark seed corpus.

Produces, under ``datasets/`` (and server-side answer keys under ``server_keys/``,
which is git-ignored to embody the trust boundary):

  Layer 1  Xodexa Public Validation Set      — 1,000 tasks across all 21 families
                                               (public answers shipped)
  Layer 2  Xodexa Private Hidden Official Set — 500 tasks across all 21 families
                                               (public views only; keys in server_keys/)
  Layer 3  Dynamic Runtime-Generated Set      — 110+ generator catalog + 100 samples

  Flagship Gauntlets  (1,000 tasks each · ±3 pt CI at 70% accuracy):
    Xodexa Code Gauntlet         — code family, all 10 subdomains
    Xodexa Agent Gauntlet        — agent family, all 10 subdomains
    Xodexa Safety Gauntlet       — all 10 security families, weighted composition

  Standard Gauntlets  (500 tasks each · ±4 pt CI at 70% accuracy):
    Xodexa Reasoning Gauntlet
    Xodexa Math Gauntlet
    Xodexa Science Gauntlet
    Xodexa Truthfulness Gauntlet
    Xodexa Multimodal Gauntlet

  Family Mini-Gauntlets  (200 tasks each · quick exploration):
    One per family for all 21 families (12 capability + 9 security)

Statistical note: 50 tasks → ±12 pt CI; 200 → ±7 pt; 500 → ±4 pt; 1000 → ±3 pt.
Focused gauntlets are sized for meaningful leaderboard discrimination.
Mini-gauntlets are developer exploration packs — not for official ranking.

    python scripts/build_seed.py            # full build
    python scripts/build_seed.py --quick    # tiny build for CI smoke test (scale=0.05)
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


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Family allocation — two-level (dimension → family) weighting
# ---------------------------------------------------------------------------

def _family_allocation(total: int, family_keys=None) -> dict[str, int]:
    """Distribute `total` tasks across families using dimension-aware weighting.

    WHY THE OLD APPROACH WAS WRONG WITH 21 FAMILIES:
    The original function looked up each family's dimension weight directly, then
    summed all weights into a ``wsum`` denominator.  With 9 new security families all
    mapping to the 'safety' dimension (weight 0.10 each), ``wsum`` inflated to 2.04
    instead of 1.0 — diluting capability families and mis-representing safety ones.

    TWO-LEVEL FIX:
      1. Allocate tasks to each *scoring dimension* proportionally by its weight.
      2. Divide that dimension's budget equally among the families that feed into it.
      3. Apply an adaptive per-family floor that scales with total / num_families,
         so --quick builds (total=50, 21 families) still produce valid output.
      4. Round-robin correction loop hits the exact target without infinite loops.

    Example for total=1000:
      safety dim (w=0.10) → 100 tasks → 10 families → 10 tasks each → floored to 12
      code   dim (w=0.12) →  120 tasks → 1 family   → 120 tasks
      agent  dim (w=0.15) →  150 tasks → 1 family   → 150 tasks
    """
    fkeys = list(family_keys) if family_keys is not None else list(families.FAMILY_KEYS)

    # Step 1 & 2: group families by dimension, then divide dimension budget
    dim_to_fams: dict[str, list[str]] = {}
    for fam in fkeys:
        dim = families.FAMILY_TO_DIMENSION.get(fam, "reasoning")
        dim_to_fams.setdefault(dim, []).append(fam)

    # Adaptive floor: scales from 2 (quick CI builds) up to ~12 (full builds).
    # Formula: total / (num_families * 4) gives sensible results across all scales.
    min_per = max(2, round(total / (len(fkeys) * 4)))

    raw: dict[str, int] = {}
    for dim, fams_in_dim in dim_to_fams.items():
        dim_weight = families.SCORE_WEIGHTS.get(dim, 0.04)
        per_fam = max(min_per, round(total * dim_weight / len(fams_in_dim)))
        for fam in fams_in_dim:
            raw[fam] = per_fam

    # Step 4: exact-total correction — adjust the largest families first to
    # minimise relative distortion, with a hard safety valve at 10k iterations.
    diff = total - sum(raw.values())
    keys_sorted = sorted(raw, key=lambda k: -raw[k])  # largest first
    i, iters = 0, 0
    while diff != 0:
        k = keys_sorted[i % len(keys_sorted)]
        if diff > 0:
            raw[k] += 1
            diff -= 1
        elif raw[k] > min_per:
            raw[k] -= 1
            diff += 1
        i += 1
        iters += 1
        if iters > len(keys_sorted) * 10_000:
            break  # safety valve — should never trigger in practice
    return raw


# ---------------------------------------------------------------------------
# Pack builder
# ---------------------------------------------------------------------------

def build_pack(name: str, version: str, family_counts: dict[str, int], *,
               visibility: str, seed: int, signer: KeyPair,
               corpus: CorpusIndex, ship_keys_publicly: bool) -> dict:
    """Generate a pack, run the pipeline, write all output files.

    Returns the manifest summary dict consumed by SUMMARY.json and datasets.html.
    """
    tasks = []
    for fam, n in family_counts.items():
        tasks += G.generate(family=fam, n=n,
                            seed=seed + hash(fam) % 9973,
                            visibility=visibility)

    rel = DatasetPipeline(corpus=corpus, signer=signer).run(
        tasks, name, version, changelog=f"Seed build of {name}")

    slug = name.lower().replace(" ", "-").replace("/", "-")
    out_dir = DATASETS / slug
    _write_jsonl(out_dir / "tasks_public_view.jsonl", rel.public_tasks)
    _write_json(out_dir / "manifest.json", rel.manifest)
    _write_json(out_dir / "manifest.sig", {
        "signature": rel.signature,
        "signer_pub": rel.manifest["signer_pub"],
    })
    _write_json(out_dir / "rejected.json", rel.rejected)

    # Answer keys: validation/public → ship alongside tasks.
    # Hidden official → server_keys/ (git-ignored; never shipped to runners).
    keys_dir = out_dir if ship_keys_publicly else SERVER_KEYS
    _write_json(keys_dir / f"{slug}.answer_keys.json", rel.answer_keys)

    return {
        "name": name,
        "version": version,
        "slug": slug,
        "task_count": rel.manifest["task_count"],
        "checksum": rel.manifest["checksum_sha256"],
        "visibility": visibility,
        "keys_location": "public" if ship_keys_publicly else "server_keys (git-ignored)",
        "families": rel.manifest["families"],
        "difficulty_bands": rel.manifest["difficulty"]["bands"],
    }


# ---------------------------------------------------------------------------
# Safety Gauntlet composition
# ---------------------------------------------------------------------------

# Weighted split across all 10 security families.
# Rationale for the distribution:
#   jailbreak_resistance — highest-profile safety failure vector → 200
#   tool_safety + rag_poisoning — primary agent-era attack surfaces → 150 each
#   safety (prompt injection / hierarchy baseline) → 100
#   privacy_security, agentic_safety, over_refusal → 100 each
#   multi_turn_manipulation → 60 (important but fewer generator variants)
#   high_stakes_safety, canary_resistance → 25 + 15 (niche but critical)
_SAFETY_GAUNTLET_FULL: dict[str, int] = {
    "safety":                   100,
    "jailbreak_resistance":     200,
    "tool_safety":              150,
    "rag_poisoning":            150,
    "privacy_security":         100,
    "agentic_safety":           100,
    "over_refusal":             100,
    "multi_turn_manipulation":   60,
    "high_stakes_safety":        25,
    "canary_resistance":         15,
}
assert sum(_SAFETY_GAUNTLET_FULL.values()) == 1000, (
    f"Safety gauntlet composition must sum to 1000, "
    f"got {sum(_SAFETY_GAUNTLET_FULL.values())}"
)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Build the Xodexa AI Benchmark seed corpus.")
    ap.add_argument("--quick", action="store_true",
                    help="Tiny build (scale=0.05) for CI smoke tests")
    args = ap.parse_args()

    signer = KeyPair.generate()
    corpus = CorpusIndex()   # production builds preload this with external corpus snippets
    scale = 0.05 if args.quick else 1.0

    def s(n: int) -> int:
        """Scale n by the build factor; minimum 2 so the pipeline always has input."""
        return max(2, round(n * scale))

    def ss(composition: dict[str, int]) -> dict[str, int]:
        """Scale every family count in an explicit composition dict."""
        return {fam: max(2, round(n * scale)) for fam, n in composition.items()}

    summary: dict = {
        "benchmark_version": "1.0.0",
        "scale": scale,
        "signer_pub": signer.pub_b64,
        "releases": [],
    }

    # -----------------------------------------------------------------------
    # Layer 1: Public Validation Set — 1,000 tasks across all 21 families
    # -----------------------------------------------------------------------
    pub_alloc = _family_allocation(s(1000))
    summary["releases"].append(build_pack(
        "Xodexa Public Validation", "1.0.0", pub_alloc,
        visibility="public", seed=1001, signer=signer, corpus=corpus,
        ship_keys_publicly=True))

    # -----------------------------------------------------------------------
    # Layer 2: Private Hidden Official Set — 500 tasks across all 21 families
    # -----------------------------------------------------------------------
    hid_alloc = _family_allocation(s(500))
    summary["releases"].append(build_pack(
        "Xodexa Hidden Official", "1.0.0", hid_alloc,
        visibility="private_hidden", seed=5005, signer=signer, corpus=corpus,
        ship_keys_publicly=False))

    # -----------------------------------------------------------------------
    # Layer 3: Dynamic generators — catalog + 100 sample variants
    # -----------------------------------------------------------------------
    catalog = [
        {
            "generator_id": gs.generator_id,
            "family": gs.family,
            "blurb": (gs.blurb or "").strip().split("\n")[0][:160],
        }
        for gs in G.list_generators()
    ]
    dyn_tasks = G.generate(n=s(100), seed=9009, visibility="dynamic")
    dyn_views = [schema.public_view(t) for t in dyn_tasks]
    _write_json(DATASETS / "dynamic" / "generator_catalog.json", {
        "generator_count": len(catalog),
        "note": (
            "Each generator yields unlimited seed-reproducible variants; "
            "answers are minted server-side per run and never shipped."
        ),
        "generators": catalog,
    })
    _write_jsonl(DATASETS / "dynamic" / "sample_variants_public_view.jsonl", dyn_views)
    summary["dynamic"] = {
        "generator_count": len(catalog),
        "sample_variants": len(dyn_views),
    }

    # -----------------------------------------------------------------------
    # Flagship Gauntlets — 1,000 tasks each (±3 pt CI at 70% accuracy)
    # Sized for reliable leaderboard discrimination at the frontier.
    # -----------------------------------------------------------------------
    flagship = [
        ("Xodexa Code Gauntlet",  {"code":  s(1000)}),
        ("Xodexa Agent Gauntlet", {"agent": s(1000)}),
        # Safety Gauntlet: explicit cross-family composition; each family scaled
        # individually so --quick still exercises every security family.
        ("Xodexa Safety Gauntlet", ss(_SAFETY_GAUNTLET_FULL)),
    ]

    # -----------------------------------------------------------------------
    # Standard Gauntlets — 500 tasks each (±4 pt CI at 70% accuracy)
    # Single-family deep dives; tight enough to rank models within ~10 pts.
    # -----------------------------------------------------------------------
    standard = [
        ("Xodexa Reasoning Gauntlet",    {"reasoning":    s(500)}),
        ("Xodexa Math Gauntlet",         {"math":         s(500)}),
        ("Xodexa Science Gauntlet",      {"science":      s(500)}),
        ("Xodexa Truthfulness Gauntlet", {"truthfulness": s(500)}),
        ("Xodexa Multimodal Gauntlet",   {"multimodal":   s(500)}),
    ]

    summary["focused_packs"] = []
    for nm, counts in flagship + standard:
        summary["focused_packs"].append(build_pack(
            nm, "1.0.0", counts,
            visibility="validation", seed=7007 + len(nm),
            signer=signer, corpus=corpus, ship_keys_publicly=True))

    # -----------------------------------------------------------------------
    # Family Mini-Gauntlets — 200 tasks each, all 21 families
    # Developer exploration packs. Use focused gauntlets for official ranking.
    # -----------------------------------------------------------------------
    summary["family_minis"] = []
    for fam in families.FAMILY_KEYS:
        summary["family_minis"].append(build_pack(
            f"Xodexa {families.FAMILIES[fam].title}", "1.0.0", {fam: s(200)},
            visibility="validation", seed=3003 + len(fam),
            signer=signer, corpus=corpus, ship_keys_publicly=True))

    _write_json(DATASETS / "SUMMARY.json", summary)

    # -----------------------------------------------------------------------
    # Console report
    # -----------------------------------------------------------------------
    print("=" * 72)
    print("  Xodexa AI Benchmark — seed corpus built")
    print("=" * 72)
    for r in summary["releases"]:
        print(f"  {r['name']:<38} {r['task_count']:>6} tasks  [{r['keys_location']}]")
    print(f"  {'Dynamic generators':<38} {summary['dynamic']['generator_count']:>6} "
          f"generators (+{summary['dynamic']['sample_variants']} sample variants)")
    print()
    print("  Flagship gauntlets (target 1,000 tasks each):")
    for p in summary["focused_packs"][:3]:
        n_fams = len(p["families"])
        fam_line = (", ".join(list(p["families"].keys())[:3])
                    + (f" +{n_fams-3} more" if n_fams > 3 else ""))
        print(f"    {p['name']:<38} {p['task_count']:>6} tasks  [{fam_line}]")
    print()
    print("  Standard gauntlets (target 500 tasks each):")
    for p in summary["focused_packs"][3:]:
        print(f"    {p['name']:<38} {p['task_count']:>6} tasks")
    print()
    n_minis = len(summary["family_minis"])
    mini_total = sum(p["task_count"] for p in summary["family_minis"])
    print(f"  Family mini-gauntlets: {n_minis} families · {mini_total:,} tasks total "
          f"(target 200 each)")
    print()
    grand_total = (
        sum(r["task_count"] for r in summary["releases"])
        + sum(p["task_count"] for p in summary["focused_packs"])
        + mini_total
        + summary["dynamic"]["sample_variants"]
    )
    print(f"  GRAND TOTAL   : {grand_total:,} tasks")
    print(f"  Output        : {DATASETS}")
    print(f"  Hidden keys   : {SERVER_KEYS} (git-ignored — never shipped)")
    print("=" * 72)


if __name__ == "__main__":
    main()
