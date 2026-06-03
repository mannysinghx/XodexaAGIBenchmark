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
                      suites)

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

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
