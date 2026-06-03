"""
xodexa.authority
==================
The central trusted Scoring Authority — the only component permitted to issue an
official Xodexa Verified Score. Everything that makes a score trustworthy lives here,
never in the runner.

Responsibilities:
  * Register runners and verify they possess their private key (challenge/response).
  * Issue server-SIGNED run manifests with a fresh nonce; derive a per-run seed so
    generated tasks are unique per run; retain answer keys server-side.
  * Verify a submitted result bundle: runner signature, manifest binding, nonce
    freshness/replay, hash-chain integrity, version allowlists.
  * RE-SCORE from raw outputs using server-held keys (the runner's score, if any, is
    advisory only).
  * Run contamination checks: canary echo, timing anomaly, suspicious perfect score.
  * Assign status (rejected / flagged / verified / verified+attested) and emit a
    signed, tamper-evident official record.

This class is storage-agnostic (in-memory dicts here; Postgres in production via the
schema in db/schema.sql). The FastAPI app wraps these methods 1:1.
"""

from __future__ import annotations

import time
import uuid

from . import suites
from .crypto import KeyPair, HashChain, sha256_hex, verify, fingerprint
from .scoring import apex_score
from .calibration import accuracy, wilson_ci, rms_calibration_error

BENCHMARK_VERSION = "1.0.0"
ALLOWED_RUNNER_VERSIONS = {"0.1.0", "0.1.1"}
# A genuine model cannot answer these gauntlet tasks faster than this; below it we
# suspect cached/looked-up answers (ANALYSIS.md §3.1 timing row).
MIN_PLAUSIBLE_MS_PER_TASK = 40.0


class ScoringAuthority:
    def __init__(self):
        self.server_key = KeyPair.generate()
        self.runners: dict[str, dict] = {}        # runner_id -> {pub, version}
        self.runs: dict[str, dict] = {}           # run_id -> server-side run state
        self.used_nonces: dict[str, str] = {}     # nonce -> run_id (replay detection)
        self.leaderboard: list[dict] = []

    # -- identity -------------------------------------------------------------
    def server_pub(self) -> str:
        return self.server_key.pub_b64

    def register_runner(self, runner_pub: str, runner_version: str) -> dict:
        runner_id = "rnr_" + uuid.uuid4().hex[:12]
        challenge = uuid.uuid4().hex
        self.runners[runner_id] = {"pub": runner_pub, "version": runner_version,
                                   "challenge": challenge, "verified": False,
                                   "fingerprint": fingerprint(runner_pub)}
        return {"runner_id": runner_id, "challenge": challenge,
                "server_pub": self.server_pub()}

    def confirm_runner(self, runner_id: str, signed_challenge: str) -> bool:
        """Runner proves possession of its private key by signing the challenge."""
        r = self.runners.get(runner_id)
        if not r:
            return False
        ok = verify(r["pub"], {"challenge": r["challenge"]}, signed_challenge)
        r["verified"] = ok
        return ok

    # -- manifest issuance ----------------------------------------------------
    def issue_manifest(self, runner_id: str, pack_id: str,
                       mode: str = "official") -> dict:
        """
        mode='official'   -> graders withheld; central-only scoring (the real thing).
        mode='comparison' -> graders shipped; runner may compute a LOCAL score that can
                             never become official.
        Returns {manifest, signature, public_tasks}. answer_keys stay server-side.
        """
        r = self.runners.get(runner_id)
        if not r or not r["verified"]:
            raise PermissionError("runner not registered/verified")

        run_id = "run_" + uuid.uuid4().hex[:16]
        nonce = uuid.uuid4().hex
        run_seed = int(sha256_hex(nonce.encode())[:12], 16)
        public_tasks, answer_keys = suites.expand_for_run(pack_id, run_seed)

        if mode == "comparison":
            # ship graders so the runner can self-score (clearly non-official)
            for t in public_tasks:
                t["grader"] = answer_keys[t["id"]]["grader"]

        manifest = {
            "run_id": run_id,
            "pack_id": pack_id,
            "pack_version": suites.PACKS[pack_id]["version"],
            "benchmark_version": BENCHMARK_VERSION,
            "mode": mode,
            "scoring": "local-allowed" if mode == "comparison" else "central-only",
            "nonce": nonce,
            "run_seed": run_seed,
            "runner_id": runner_id,
            "task_ids": [t["id"] for t in public_tasks],
            "canary_policy": "no-echo",
            "issued_at": time.time(),
            "server_pub": self.server_pub(),
        }
        signature = self.server_key.sign(manifest)
        manifest_hash = sha256_hex(manifest)
        self.runs[run_id] = {
            "manifest": manifest, "manifest_hash": manifest_hash,
            "answer_keys": answer_keys, "finalized": False, "mode": mode,
        }
        self.used_nonces[nonce] = run_id
        return {"manifest": manifest, "signature": signature,
                "public_tasks": public_tasks}

    # -- verification + central scoring --------------------------------------
    def verify_and_score(self, bundle: dict) -> dict:
        checks: list[dict] = []

        def check(name, ok, detail=""):
            checks.append({"check": name, "ok": bool(ok), "detail": detail})
            return ok

        report = {"run_id": bundle.get("run_id"), "checks": checks}
        run = self.runs.get(bundle.get("run_id"))

        # --- hard integrity gates (any failure => REJECT) ---
        if not check("run_known", run is not None, "manifest was issued by this server"):
            report["status"] = "rejected"
            return report
        if not check("not_duplicate", not run["finalized"], "run not already finalized"):
            report["status"] = "rejected"
            return report

        runner = self.runners.get(bundle.get("runner_id"))
        check("runner_registered", runner is not None and runner["verified"])

        sig = bundle.get("signature")
        core = {k: v for k, v in bundle.items() if k != "signature"}
        sig_ok = runner is not None and verify(runner["pub"], core, sig or "")
        check("runner_signature", sig_ok, "Ed25519 signature over result bundle")

        mh_ok = bundle.get("manifest_hash") == run["manifest_hash"]
        check("manifest_binding", mh_ok, "bundle bound to the issued manifest")

        nonce_ok = self.used_nonces.get(run["manifest"]["nonce"]) == bundle.get("run_id")
        check("nonce_freshness", nonce_ok, "no nonce replay across runs")

        ver_ok = (runner or {}).get("version") in ALLOWED_RUNNER_VERSIONS
        check("runner_version_allowed", ver_ok,
              f"runner version in {sorted(ALLOWED_RUNNER_VERSIONS)}")

        # hash-chain integrity
        entries = (bundle.get("event_log") or {}).get("entries", [])
        chain_ok, chain_head = HashChain.verify(entries)
        head_match = chain_ok and chain_head == (bundle.get("event_log") or {}).get("head")
        check("event_log_chain", head_match, "hash-chained log intact & head matches")

        if not (sig_ok and mh_ok and nonce_ok and head_match):
            report["status"] = "rejected"
            report["reason"] = "failed a hard integrity gate"
            return report

        # --- central re-scoring from RAW outputs (server-held keys) ---
        keys = run["answer_keys"]
        responses = {r["id"]: r for r in bundle.get("responses", [])}
        item_results, canary_hits, fast_tasks = [], 0, 0
        per_item = []
        correct_flags, confidences = [], []
        for tid, key in keys.items():
            resp = responses.get(tid, {})
            output = resp.get("output", "")
            awarded, mx, verdict = suites.grade_response(key, output)
            item_results.append({"category": key["category"], "awarded": awarded,
                                 "max": mx})
            # HLE-style binary correctness (>= half credit) for accuracy + calibration
            is_correct = 1 if (mx and awarded >= 0.5 * mx) else 0
            correct_flags.append(is_correct)
            if "confidence" in resp:
                confidences.append(float(resp["confidence"]))
            if key["canary"] in (output or ""):
                canary_hits += 1
            if float(resp.get("latency_ms", 9e9)) < MIN_PLAUSIBLE_MS_PER_TASK:
                fast_tasks += 1
            per_item.append({"id": tid, "category": key["category"],
                             "awarded": round(awarded, 3), "max": mx, "verdict": verdict})

        # --- contamination / anomaly signals ---
        n = max(1, len(keys))
        total_aw = sum(r["awarded"] for r in item_results)
        total_mx = sum(r["max"] for r in item_results)
        frac = total_aw / total_mx if total_mx else 0
        external = {}
        if canary_hits:
            external["canary_leakage"] = min(1.0, canary_hits / n)
            check("canary_no_echo", False, f"{canary_hits} canary echo(es) detected")
        else:
            check("canary_no_echo", True, "no canary tokens echoed")

        if fast_tasks / n > 0.5:
            external["timing_anomaly"] = min(1.0, fast_tasks / n)
            check("timing_plausible", False, f"{fast_tasks}/{n} tasks implausibly fast")
        else:
            check("timing_plausible", True, "task latencies plausible")

        if frac >= 0.97:
            external["contamination_risk"] = 0.5
            check("score_distribution", False, "suspiciously near-perfect score")
        else:
            check("score_distribution", True, "score within expected distribution")

        # --- HLE-style honesty metrics (accuracy + calibration) ---
        n_correct = sum(correct_flags)
        acc_point, acc_half, _ = wilson_ci(n_correct, len(correct_flags))
        calib_err = (rms_calibration_error(confidences, correct_flags)
                     if len(confidences) == len(correct_flags) and confidences else None)
        report["frontier_metrics"] = {
            "accuracy": acc_point,            # 0-100, exact-match style
            "accuracy_ci95": acc_half,        # ± half-width
            "calibration_error": calib_err,   # 0-100 RMS-CE, None if no confidences
            "n": len(correct_flags),
        }
        # Overconfidence penalty: poor calibration feeds the truthfulness signal.
        if calib_err is not None and calib_err > 50:
            external["overconfidence"] = min(1.0, (calib_err - 50) / 50)

        # --- Xodexa Score (central, authoritative) ---
        report["apex"] = apex_score(item_results, external_signals=external)
        report["per_item"] = per_item

        # --- status assignment ---
        attested = (bundle.get("environment", {}).get("attestation", "none") != "none")
        flagged = bool(external)
        if flagged:
            report["status"] = "flagged"
            report["verification_status"] = "Flagged for review"
        else:
            report["status"] = "verified"
            report["verification_status"] = ("Verified + Attested" if attested
                                             else "Verified, non-attested")
        report["attestation"] = bundle.get("environment", {}).get("attestation", "none")

        # finalize + sign the official record (tamper-evident)
        run["finalized"] = True
        official = {
            "run_id": bundle["run_id"], "model_id": bundle.get("model_id"),
            "pack_id": run["manifest"]["pack_id"],
            "benchmark_version": BENCHMARK_VERSION,
            "apex_score": report["apex"]["apex_score"], "grade": report["apex"]["grade"],
            "ci95": report["apex"]["ci95"], "coverage": report["apex"]["coverage"],
            "verification_status": report["verification_status"],
            "attestation": report["attestation"], "issued_at": time.time(),
            "accuracy": report["frontier_metrics"]["accuracy"],
            "accuracy_ci95": report["frontier_metrics"]["accuracy_ci95"],
            "calibration_error": report["frontier_metrics"]["calibration_error"],
        }
        report["official_record"] = official
        report["official_signature"] = self.server_key.sign(official)

        if report["status"] in ("verified",):
            self.leaderboard.append(official)
        return report
