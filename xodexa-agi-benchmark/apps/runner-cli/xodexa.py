#!/usr/bin/env python3
"""
xodexa — the open-source Xodexa AGI Benchmark runner CLI.

Two operating modes:
  * --server URL : talk to a live Xodexa main app over HTTP (register/run/submit).
  * --local      : self-contained demo that stands up an in-process authority so you
                   can exercise the full flow with no server (handy for development and
                   for proving the runner cannot self-issue official scores).

Commands (subset of the full spec, the ones that are wired):
  xodexa benchmark list
  xodexa run    --model <connector> --suite <pack> [--mode official|comparison] [--local]
  xodexa verify <bundle.json>
  xodexa export --run <report.json> --format json|markdown
  xodexa status

Model connectors for --model:
  callable:good           built-in simulated competent model (local demo only)
  callable:bluffer        built-in simulated hallucinating model (local demo only)
  openai:<base_url>#<m>   any OpenAI-compatible endpoint (vLLM/TGI/Ollama/LM Studio/...)
  ollama:<base_url>#<m>   native Ollama endpoint
"""

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

from xodexa import (ScoringAuthority, RunnerAgent, CallableConnector,  # noqa: E402
                      OpenAICompatibleConnector, OllamaConnector, HashChain, verify,
                      suites, families, generators as gens, schema, grade, evaluate,
                      report as report_mod, anchors)

RESULTS = Path("./results")


def _xodex():
    p = ROOT.parent / "xodex_omega" / "harness.py"
    spec = importlib.util.spec_from_file_location("xodex_cli", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_connector(spec_str, authority=None, run_id=None):
    if spec_str.startswith("callable:"):
        kind = spec_str.split(":", 1)[1]
        H = _xodex()
        keys = authority.runs[run_id]["answer_keys"]
        order = list(keys.keys())
        ans = {}
        for i, (tid, k) in enumerate(keys.items()):
            item = {"grader": k["grader"], "points": k["points"], "negative": k["negative"]}
            ans[tid] = H.synth_bad(item) if kind == "bluffer" else (
                H.synth_bad(item) if i % 4 == 0 else H.synth_good(item))
        c = {"i": 0}

        def fn(prompt):
            tid = order[c["i"]]
            c["i"] += 1
            time.sleep(0.05)
            return ans[tid]
        return CallableConnector(fn, name=spec_str)
    if spec_str.startswith("openai:"):
        rest = spec_str.split(":", 1)[1]
        base, model = rest.split("#", 1)
        return OpenAICompatibleConnector(base, model)
    if spec_str.startswith("ollama:"):
        rest = spec_str.split(":", 1)[1]
        base, model = rest.split("#", 1)
        return OllamaConnector(base, model)
    raise SystemExit(f"unknown connector spec: {spec_str}")


def cmd_list(args):
    print("Available benchmark packs:\n")
    for pid, p in suites.list_packs().items():
        print(f"  {pid:<22} v{p['version']:<7} {', '.join(p['categories'])}")
        print(f"  {'':<22} {p['description']}")
    return 0


def cmd_run(args):
    RESULTS.mkdir(exist_ok=True)
    if not args.local:
        print("HTTP mode talks to --server; for this offline build use --local.",
              file=sys.stderr)
        if not args.server:
            return 2
    authority = ScoringAuthority()
    runner = RunnerAgent()
    runner.register(authority)
    issued = authority.issue_manifest(runner.runner_id, args.suite, mode=args.mode)
    run_id = issued["manifest"]["run_id"]
    conn = build_connector(args.model, authority, run_id)
    print(f"running {args.suite} ({args.mode}) with {conn.name} ...")
    bundle = runner.execute(issued, conn, model_id=args.model,
                            attestation=args.attestation)
    bundle_path = RESULTS / f"{run_id}.bundle.json"
    bundle_path.write_text(json.dumps(bundle, indent=2))

    report = authority.verify_and_score(bundle)
    report_path = RESULTS / f"{run_id}.report.json"
    report_path.write_text(json.dumps(report, indent=2))

    if "local_score" in bundle:
        ls = bundle["local_score"]
        print(f"  LOCAL score: {ls['pct']}%  ({ls['label']})")
    if "apex" in report:
        ap = report["apex"]
        print(f"  APEX score : {ap['apex_score']} ±{ap['ci95']}  grade={ap['grade']}  "
              f"coverage={ap['coverage_label']}")
        print(f"  status     : {report.get('verification_status', report['status'])}")
    else:
        print(f"  status     : {report['status']}  (no official score issued)")
    print(f"  saved      : {bundle_path}  +  {report_path}")
    return 0


def cmd_verify(args):
    bundle = json.loads(Path(args.bundle).read_text())
    core = {k: v for k, v in bundle.items() if k != "signature"}
    entries = bundle.get("event_log", {}).get("entries", [])
    chain_ok, head = HashChain.verify(entries)
    head_match = chain_ok and head == bundle.get("event_log", {}).get("head")
    print(f"event_log_chain : {'OK' if head_match else 'BROKEN'}")
    print("signature       : present" if bundle.get("signature") else "signature: MISSING")
    print("note            : full signature + manifest + nonce verification is performed")
    print("                  server-side by the Xodexa main app, not by the runner.")
    return 0 if head_match else 1


def cmd_export(args):
    rep = json.loads(Path(args.run).read_text())
    if args.format == "json":
        print(json.dumps(rep, indent=2))
        return 0
    ap = rep.get("apex", {})
    md = [f"# Xodexa Report — {rep.get('run_id','')}", "",
          f"- **Xodexa Score**: {ap.get('apex_score','N/A')} (CI95 {ap.get('ci95','')})",
          f"- **Grade**: {ap.get('grade','N/A')}",
          f"- **Coverage**: {ap.get('coverage_label','N/A')}",
          f"- **Verification**: {rep.get('verification_status', rep.get('status'))}", "",
          "## Checks"]
    for c in rep.get("checks", []):
        md.append(f"- {'✅' if c['ok'] else '❌'} {c['check']} — {c['detail']}")
    print("\n".join(md))
    return 0


def cmd_status(args):
    print("xodexa runner 0.1.0")
    print("mode: offline/local-capable")
    print("connectors: callable, openai-compatible, ollama")
    print("note: official scores are issued ONLY by the Xodexa main app.")
    return 0


# --------------------------------------------------------------------------- #
# Platform-layer commands (catalog browsing, dataset generation, local eval)
# --------------------------------------------------------------------------- #

def cmd_families(args):
    print("Xodexa task families (12):\n")
    for k, f in families.FAMILIES.items():
        dim = families.FAMILY_TO_DIMENSION[k]
        print(f"  {k:<14} {f.title}")
        print(f"  {'':<14} -> dimension '{dim}' (weight "
              f"{families.SCORE_WEIGHTS.get(dim, 0):.0%})")
    print("\nScoring dimensions (weights sum to 1.0):")
    for d, w in families.SCORE_WEIGHTS.items():
        print(f"  {d:<18} {w:.0%}")
    print("\nAGI Readiness levels:")
    for L in families.AGI_LEVELS:
        print(f"  L{L.level}  {L.name}")
    return 0


def cmd_generators(args):
    specs = gens.list_generators(args.family)
    print(f"{len(specs)} procedural generators"
          + (f" for family '{args.family}'" if args.family else "") + ":\n")
    for s in specs:
        print(f"  {s.generator_id:<34} [{s.family}]")
    print("\nEach generator yields unlimited seed-reproducible variants.")
    return 0


def cmd_anchors(args):
    a = anchors.list_anchors(args.dimension)
    summ = anchors.contamination_summary()
    print(f"Layer-0 public calibration anchors ({summ['total_anchors']}), "
          f"contamination risk {summ['by_contamination_risk']}:\n")
    for x in a:
        print(f"  {x.name:<28} dim={x.dimension:<16} risk={x.contamination_risk:<6} "
              f"license={x.license}")
    print("\nThese calibrate/contextualize only — never the official Xodexa Score.")
    return 0


def cmd_dataset_generate(args):
    RESULTS.mkdir(exist_ok=True)
    tasks = gens.generate(family=args.family, n=args.n, seed=args.seed,
                          visibility=args.visibility)
    rows = [schema.public_view(t) for t in tasks]
    out = Path(args.out) if args.out else RESULTS / f"generated_{args.family or 'mixed'}.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in rows))
    print(f"generated {len(rows)} {args.visibility} tasks"
          + (f" (family={args.family})" if args.family else " (all families)"))
    print(f"  public views (no answers/graders) -> {out}")
    return 0


def _simulate_responses(keys, kind):
    """Build responses for the built-in simulated models (callable:*)."""
    import random as _r
    rng = _r.Random(0)
    responses = []
    for i, (tid, key) in enumerate(keys.items()):
        g = key["grader"]
        if kind == "good":
            ok = True
        elif kind == "bad":
            ok = False
        else:  # mixed
            ok = (i % 3 != 0)
        out = grade.synth_good(g) if ok else grade.synth_bad(g)
        conf = rng.uniform(0.6, 0.95) if ok else rng.uniform(0.75, 0.99)
        responses.append({"id": tid, "output": out, "confidence": round(conf, 3),
                          "latency_ms": rng.uniform(700, 2500)})
    return responses


def cmd_evaluate(args):
    """Generate a pack locally, run a model, centrally re-score IN-PROCESS, and emit a
    full platform report (Xodexa Score + AGI Readiness). LOCAL = not official."""
    RESULTS.mkdir(exist_ok=True)
    tasks = gens.generate(family=args.family, n=args.n, seed=args.seed,
                          visibility="validation")
    keys = {t.task_id: schema.answer_key(t) for t in tasks}

    if args.model.startswith("callable:"):
        kind = args.model.split(":", 1)[1]
        responses = _simulate_responses(keys, kind)
    else:
        conn = build_connector(args.model)
        responses = []
        for t in tasks:
            t0 = time.perf_counter()
            out = conn.complete(t.prompt)
            responses.append({"id": t.task_id, "output": out,
                              "latency_ms": (time.perf_counter() - t0) * 1000})

    er = evaluate.score_pack(keys, responses)
    rep = report_mod.build_report(args.model, f"local:{args.family or 'mixed'}", er,
                                  telemetry={"tokens": sum(len(r.get("output", "")) // 4
                                                           for r in responses)})
    rep["_label"] = "UNVERIFIED LOCAL SCORE — not eligible for the official leaderboard"
    path = RESULTS / f"local_report_{args.model.replace(':', '_')}.json"
    path.write_text(json.dumps(rep, indent=2))

    ar = rep["agi_readiness"]
    print("=" * 64)
    print(f"  UNVERIFIED LOCAL EVALUATION — {args.model}")
    print("=" * 64)
    print(f"  Xodexa Score : {rep['xodexa_score']}/1000  ({rep['grade']})  "
          f"coverage {rep['coverage']}")
    print(f"  AGI Readiness: Level {ar['level']} — {ar['level_name']} "
          f"(index {ar['agi_readiness_index']})")
    print(f"  Accuracy     : {rep['frontier_metrics']['accuracy']}% "
          f"± {rep['frontier_metrics']['accuracy_ci95']}")
    print(f"  Failure rate : {rep['failure_analysis']['failure_rate']:.0%} "
          f"({rep['failure_analysis']['total_failures']}/{rep['failure_analysis']['total_items']})")
    print(f"  Top gap      : {ar['missing_capability']}")
    print(f"  Next evals   : {', '.join(rep['next_recommended_benchmarks'][:3])}")
    print(f"  saved        : {path}")
    print("  NOTE: official scores are issued ONLY by the Xodexa main app.")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="xodexa", description="Xodexa AGI Benchmark runner CLI")
    ap.add_argument("--server", help="Xodexa main app base URL")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("benchmark")
    bsub = b.add_subparsers(dest="bcmd", required=True)
    bl = bsub.add_parser("list")
    bl.set_defaults(func=cmd_list)

    r = sub.add_parser("run")
    r.add_argument("--model", required=True)
    r.add_argument("--suite", default="xodexa-omega")
    r.add_argument("--mode", choices=["official", "comparison"], default="official")
    r.add_argument("--attestation", default="none")
    r.add_argument("--local", action="store_true")
    r.set_defaults(func=cmd_run)

    v = sub.add_parser("verify")
    v.add_argument("bundle")
    v.set_defaults(func=cmd_verify)

    e = sub.add_parser("export")
    e.add_argument("--run", required=True)
    e.add_argument("--format", choices=["json", "markdown"], default="markdown")
    e.set_defaults(func=cmd_export)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    fam = sub.add_parser("families", help="list the 12 task families + scoring weights")
    fam.set_defaults(func=cmd_families)

    g = sub.add_parser("generators", help="list procedural task generators (Layer 3)")
    g.add_argument("--family")
    g.set_defaults(func=cmd_generators)

    an = sub.add_parser("anchors", help="list Layer-0 public calibration benchmarks")
    an.add_argument("--dimension")
    an.set_defaults(func=cmd_anchors)

    d = sub.add_parser("dataset")
    dsub = d.add_subparsers(dest="dcmd", required=True)
    dg = dsub.add_parser("generate", help="generate public-view tasks to JSONL")
    dg.add_argument("--family")
    dg.add_argument("--n", type=int, default=20)
    dg.add_argument("--seed", type=int, default=0)
    dg.add_argument("--visibility", default="dynamic",
                    choices=["public", "validation", "private_hidden", "dynamic"])
    dg.add_argument("--out")
    dg.set_defaults(func=cmd_dataset_generate)

    ev = sub.add_parser("evaluate", help="LOCAL eval -> Xodexa Score + AGI Readiness")
    ev.add_argument("--model", required=True,
                    help="callable:good|bad|mixed, or openai:<base>#<model>, ollama:<base>#<model>")
    ev.add_argument("--family", help="restrict to one family (default: all)")
    ev.add_argument("--n", type=int, default=60)
    ev.add_argument("--seed", type=int, default=0)
    ev.set_defaults(func=cmd_evaluate)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
