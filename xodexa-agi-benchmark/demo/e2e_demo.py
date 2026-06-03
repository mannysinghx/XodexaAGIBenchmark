#!/usr/bin/env python3
"""
Xodexa AGI Benchmark — end-to-end trust-kernel demonstration.

Proves, with real Ed25519 crypto and the real Xodexa-Ω gauntlet as the engine, that:

  1. A self-hosted runner registers by PROVING possession of its private key.
  2. The server issues a SIGNED manifest; the runner refuses to run an unsigned one.
  3. COMPARISON mode ships graders -> runner gets a LOCAL (non-official) score.
  4. OFFICIAL mode withholds graders -> the runner submits RAW outputs only, and the
     SERVER produces the one authoritative Xodexa Verified Score by re-scoring centrally.
  5. Contamination defenses fire: canary echo, timing anomaly, suspicious perfect score.
  6. Tampering FAILS CLOSED: editing a response or the hash-chained log => REJECTED.

The "models" here are simulated personas. To simulate a model of a given competence we
use the gauntlet's own synthetic-answer generators against the server-held keys — this
is a TEST FIXTURE only; it stands in for whatever real model a runner would call via a
connector. Nothing in the trust path depends on it.
"""

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from xodexa import ScoringAuthority, RunnerAgent, CallableConnector  # noqa: E402

# load Xodexa-Ω synthetic answer generators (fixture only)
_xodex = ROOT.parent / "xodex_omega" / "harness.py"
_spec = importlib.util.spec_from_file_location("xodex_fixture", _xodex)
H = importlib.util.module_from_spec(_spec)
sys.modules["xodex_fixture"] = H
_spec.loader.exec_module(H)


def line(c="="):
    print(c * 78)


def persona_connector(authority, run_id, kind, latency_s=0.05):
    """
    Build a model connector that simulates a model of competence `kind`, by mapping
    each task's prompt to a synthetic answer derived from the server-held grader.
    """
    keys = authority.runs[run_id]["answer_keys"]
    # map prompt-prefix -> task_id so the connector can answer by prompt
    # (the runner passes the canary-augmented prompt; we key on task id via a closure)
    answers = {}
    for i, (tid, key) in enumerate(keys.items()):
        item = {"grader": key["grader"], "points": key["points"], "negative": key["negative"]}
        if kind == "near_perfect":
            ans = H.synth_good(item)
        elif kind == "bluffer":
            ans = H.synth_bad(item)
        elif kind == "canary_leaker":
            ans = H.synth_good(item) + " " + key["canary"]   # echoes the canary
        else:  # "strong": competent but imperfect (misses ~1 in 4)
            ans = H.synth_bad(item) if (i % 4 == 0) else H.synth_good(item)
        answers[tid] = ans

    # Stated confidence per persona (drives HLE-style calibration error).
    conf = {"strong": 0.65, "near_perfect": 0.9, "bluffer": 0.9,
            "canary_leaker": 0.7}.get(kind, 0.7)
    order = list(keys.keys())
    counter = {"i": 0}

    def fn(prompt):
        tid = order[counter["i"]]
        counter["i"] += 1
        if latency_s:
            time.sleep(latency_s)
        return (answers[tid], conf)          # (text, confidence)

    return CallableConnector(fn, name=f"sim-{kind}")


def run_official(authority, runner, pack, kind, latency_s, attestation="none"):
    issued = authority.issue_manifest(runner.runner_id, pack, mode="official")
    conn = persona_connector(authority, issued["manifest"]["run_id"], kind, latency_s)
    bundle = runner.execute(issued, conn, model_id=f"demo/{kind}", attestation=attestation)
    report = authority.verify_and_score(bundle)
    return issued, bundle, report


def main():
    line()
    print("  APEXAGI BENCH — END-TO-END TRUST KERNEL DEMO")
    print("  engine: Xodexa-Ω gauntlet   crypto: Ed25519   scoring: central-only")
    line()

    authority = ScoringAuthority()
    runner = RunnerAgent()
    rid = runner.register(authority)
    print(f"\n[1] Runner registered & key-challenge verified.  runner_id={rid}")
    print(f"    server pubkey fp = {authority.runners[rid]['fingerprint']}")
    pack = "xodexa-omega"

    # --- 2. Refuse unsigned/forged manifest ---
    issued = authority.issue_manifest(rid, pack, mode="comparison")
    forged = {"manifest": {**issued["manifest"], "nonce": "tampered"},
              "signature": issued["signature"], "public_tasks": issued["public_tasks"]}
    try:
        runner.execute(forged, persona_connector(authority, issued["manifest"]["run_id"],
                                                  "strong"), "x")
        print("\n[2] FAIL: runner accepted a forged manifest")
    except RuntimeError as e:
        print(f"\n[2] Forged manifest correctly REFUSED by runner: {e}")

    # --- 3. Comparison mode -> LOCAL score ---
    issued = authority.issue_manifest(rid, pack, mode="comparison")
    conn = persona_connector(authority, issued["manifest"]["run_id"], "strong")
    cbundle = runner.execute(issued, conn, model_id="demo/strong")
    ls = cbundle["local_score"]
    print(f"\n[3] COMPARISON run -> {ls['label']}: {ls['pct']}%  ({ls['raw']}/{ls['max']})")
    print("    (graders were shipped; this score can NEVER become official)")

    # --- 4..6. Official runs across personas ---
    print("\n[4] OFFICIAL runs (graders withheld; server re-scores raw outputs):\n")
    print(f"    {'persona':<16}{'apex':>7}{'grade':>22}  status / signals")
    print("    " + "-" * 70)
    scenarios = [
        ("strong",        0.05, "none"),
        ("strong+attest", 0.05, "nitro"),
        ("near_perfect",  0.05, "none"),
        ("bluffer",       0.05, "none"),
        ("canary_leaker", 0.05, "none"),
        ("cached_fast",   0.0,  "none"),
    ]
    strong_bundle = None
    for label, lat, att in scenarios:
        kind = "strong" if label in ("strong+attest", "cached_fast") else label
        _, bundle, rep = run_official(authority, runner, pack, kind, lat, att)
        if label == "strong":
            strong_bundle = bundle
            strong_run_id = bundle["run_id"]
        ax = rep["apex"]["apex_score"]
        gr = rep["apex"]["grade"]
        signals = ",".join(rep["apex"]["external_penalties_applied"].keys()) or "clean"
        vs = rep.get("verification_status", rep["status"])
        print(f"    {label:<16}{ax:>7}{gr:>22}  {rep['status']}/{vs} [{signals}]")

    # --- detail for the clean verified run ---
    line("-")
    print("  Detail — clean OFFICIAL 'strong' run (the authoritative result):")
    # re-run a fresh strong to show full report (previous strong is finalized)
    _, sb, srep = run_official(authority, runner, pack, "strong", 0.05, "none")
    ap = srep["apex"]
    fm = srep["frontier_metrics"]
    print(f"    Xodexa Score      : {ap['apex_score']}  ± CI95 {ap['ci95']}   grade={ap['grade']}")
    print(f"    HLE-style       : accuracy {fm['accuracy']:.2f} ±{fm['accuracy_ci95']:.2f}   "
          f"calibration error {fm['calibration_error']}")
    print(f"    Coverage        : {ap['coverage_label']}  ({ap['coverage']*100:.0f}% of categories)")
    print(f"    Verification    : {srep['verification_status']}  (attestation={srep['attestation']})")
    print(f"    Categories      :")
    for c, d in ap["categories"].items():
        print(f"        {c:<14} {d['score']*1000:6.1f}/1000  (w={d['weight']}, n={d['n']})")
    print(f"    Not evaluated   : {', '.join(ap['categories_not_evaluated'])}")
    print(f"    Checks passed   : {sum(1 for c in srep['checks'] if c['ok'])}/{len(srep['checks'])}")

    # --- 7. Tamper tests (must FAIL CLOSED) ---
    line()
    print("  [7] TAMPER TESTS — a modified bundle must be REJECTED\n")

    # 7a: edit a model output after signing
    import copy
    t1 = copy.deepcopy(strong_bundle)
    t1["run_id"] = strong_run_id  # same run, but it's finalized -> also duplicate
    # use a fresh official run so we test signature, not duplicate:
    iss, fresh, _ = run_official(authority, runner, pack, "strong", 0.05)
    # Note: fresh was already submitted+finalized. For a pure signature test, craft a
    # new run and tamper BEFORE submit:
    iss2 = authority.issue_manifest(rid, pack, mode="official")
    conn2 = persona_connector(authority, iss2["manifest"]["run_id"], "strong")
    good = runner.execute(iss2, conn2, model_id="demo/strong")
    tampered = copy.deepcopy(good)
    tampered["responses"][0]["output"] = "INJECTED ANSWER"  # change a raw output
    rep_t = authority.verify_and_score(tampered)
    sig_check = next(c for c in rep_t["checks"] if c["check"] == "runner_signature")
    print(f"    7a edit a response  -> status={rep_t['status']}  "
          f"(runner_signature ok={sig_check['ok']})")

    # 7b: edit the hash-chained event log
    iss3 = authority.issue_manifest(rid, pack, mode="official")
    conn3 = persona_connector(authority, iss3["manifest"]["run_id"], "strong")
    good3 = runner.execute(iss3, conn3, model_id="demo/strong")
    tampered2 = copy.deepcopy(good3)
    tampered2["event_log"]["entries"][1]["event"]["data"]["latency_ms"] = 0.001
    # re-sign so the signature passes, to isolate the CHAIN check
    core2 = {k: v for k, v in tampered2.items() if k != "signature"}
    tampered2["signature"] = runner.key.sign(core2)
    rep_t2 = authority.verify_and_score(tampered2)
    chain_check = next(c for c in rep_t2["checks"] if c["check"] == "event_log_chain")
    print(f"    7b edit event log   -> status={rep_t2['status']}  "
          f"(event_log_chain ok={chain_check['ok']})")

    # 7c: replay a manifest (submit twice)
    iss4 = authority.issue_manifest(rid, pack, mode="official")
    conn4 = persona_connector(authority, iss4["manifest"]["run_id"], "strong")
    good4 = runner.execute(iss4, conn4, model_id="demo/strong")
    authority.verify_and_score(good4)              # first submit -> finalizes
    rep_dup = authority.verify_and_score(good4)    # second submit -> duplicate
    dup_check = next(c for c in rep_dup["checks"] if c["check"] == "not_duplicate")
    print(f"    7c replay/duplicate -> status={rep_dup['status']}  "
          f"(not_duplicate ok={dup_check['ok']})")

    # --- summary assertions ---
    line()
    ok = (rep_t["status"] == "rejected" and not sig_check["ok"]
          and rep_t2["status"] == "rejected" and not chain_check["ok"]
          and rep_dup["status"] == "rejected" and not dup_check["ok"]
          and srep["status"] == "verified")
    print(f"  LEADERBOARD (verified entries published): {len(authority.leaderboard)}")
    print(f"\n  DEMO {'PASSED ✓ — trust kernel behaves correctly' if ok else 'FAILED ✗'}")
    line()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
