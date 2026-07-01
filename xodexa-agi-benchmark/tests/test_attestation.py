#!/usr/bin/env python3
"""
test_attestation.py — tests for the hardware-attestation verification interface.

These lock in the module's core honesty property: the verifier DEFAULTS to
"none"/"unverified" and never fabricates an "attested: true". A genuine "verified"
is reachable only when an injected vendor-root verifier vouches for the quote AND
every structural/binding check passes.

Runs with pytest OR standalone:  python tests/test_attestation.py
Covers: none/missing, nonce binding, measurement allow-listing, the honest
"unverified" ceiling without a root verifier, a passing root verifier, a failing
root verifier, and an end-to-end authority run that carries the new report block
without changing the existing "Verified, non-attested" status.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))  # beat any shadow 'xodexa'

from xodexa import ScoringAuthority, RunnerAgent, CallableConnector  # noqa: E402
from xodexa.attestation import (  # noqa: E402
    AttestationDoc,
    VerificationResult,
    parse_attestation,
    verify_attestation,
    attestation_status_for_report,
)

NONCE = "a" * 32
GOOD_MEASUREMENT = "pcr0:deadbeef"


def _full_doc(nonce=NONCE, platform="nitro", measurement=GOOD_MEASUREMENT):
    """A structurally-complete quote document bound to `nonce`."""
    return {
        "platform": platform,
        "measurement": measurement,
        "nonce": nonce,
        "signature": "c2lnbmF0dXJl",           # base64-ish opaque blob
        "cert_chain": ["-----leaf-----", "-----root-----"],
    }


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def test_parse_none_and_missing():
    assert parse_attestation(None).platform == "none"
    assert parse_attestation("none").platform == "none"
    assert parse_attestation("").platform == "none"
    assert parse_attestation({}).platform == "none"
    assert parse_attestation("garbage-platform").platform == "none"
    # A bare legacy string platform survives.
    assert parse_attestation("nitro").platform == "nitro"


def test_parse_full_doc():
    doc = parse_attestation(_full_doc())
    assert doc.platform == "nitro"
    assert doc.nonce == NONCE
    assert doc.measurement == GOOD_MEASUREMENT
    assert doc.has_structure and doc.is_present
    # cert_chain given as a bare string is coerced to a list.
    d2 = parse_attestation({"platform": "tdx", "cert_chain": "onecert",
                            "signature": "x", "nonce": NONCE})
    assert d2.cert_chain == ["onecert"]


# --------------------------------------------------------------------------- #
# none / missing -> status "none", not an error
# --------------------------------------------------------------------------- #

def test_none_status_is_default_not_error():
    for supplied in (None, "none", {}, "unknown"):
        res = verify_attestation(parse_attestation(supplied), expected_nonce=NONCE)
        assert isinstance(res, VerificationResult)
        assert res.status == "none", supplied
        assert res.measurement_matched is False
        assert res.nonce_matched is False


# --------------------------------------------------------------------------- #
# nonce mismatch -> "invalid" with reason
# --------------------------------------------------------------------------- #

def test_nonce_mismatch_is_invalid():
    doc = parse_attestation(_full_doc(nonce="wrong-nonce"))
    res = verify_attestation(doc, expected_nonce=NONCE)
    assert res.status == "invalid"
    assert res.nonce_matched is False
    assert any("nonce" in r for r in res.reasons)


def test_empty_expected_nonce_cannot_pass():
    doc = parse_attestation(_full_doc(nonce=""))
    res = verify_attestation(doc, expected_nonce="")
    assert res.status == "invalid"
    assert res.nonce_matched is False


# --------------------------------------------------------------------------- #
# measurement not in trusted set -> measurement_matched False
# --------------------------------------------------------------------------- #

def test_unknown_measurement_not_matched():
    doc = parse_attestation(_full_doc(measurement="pcr0:unexpected"))
    res = verify_attestation(doc, expected_nonce=NONCE,
                             trusted_measurements=[GOOD_MEASUREMENT])
    assert res.measurement_matched is False
    assert res.status == "unverified"
    assert any("unknown measurement" in r for r in res.reasons)


# --------------------------------------------------------------------------- #
# structure present + nonce ok + measurement trusted but NO root verifier
#   -> honest default "unverified"
# --------------------------------------------------------------------------- #

def test_no_root_verifier_is_unverified():
    doc = parse_attestation(_full_doc())
    res = verify_attestation(doc, expected_nonce=NONCE,
                             trusted_measurements=[GOOD_MEASUREMENT])
    assert res.status == "unverified"           # <-- the honest ceiling
    assert res.nonce_matched is True
    assert res.measurement_matched is True
    assert any("no trusted-root verifier configured" in r for r in res.reasons)


def test_missing_structure_is_invalid():
    # nonce ok but no signature / cert_chain -> not a real quote.
    doc = parse_attestation({"platform": "nitro", "nonce": NONCE,
                             "measurement": GOOD_MEASUREMENT})
    res = verify_attestation(doc, expected_nonce=NONCE)
    assert res.status == "invalid"
    assert any("structure" in r for r in res.reasons)


# --------------------------------------------------------------------------- #
# root verifier returning True + all checks pass -> "verified"
# --------------------------------------------------------------------------- #

def test_root_verifier_true_yields_verified():
    doc = parse_attestation(_full_doc())

    def verifier(d: AttestationDoc) -> bool:
        assert isinstance(d, AttestationDoc)
        return True

    res = verify_attestation(doc, expected_nonce=NONCE,
                             trusted_measurements=[GOOD_MEASUREMENT],
                             trusted_roots=verifier)
    assert res.status == "verified"
    assert res.nonce_matched and res.measurement_matched


# --------------------------------------------------------------------------- #
# root verifier returning False (or raising) -> "unverified", never a fake pass
# --------------------------------------------------------------------------- #

def test_root_verifier_false_yields_unverified():
    doc = parse_attestation(_full_doc())
    res = verify_attestation(doc, expected_nonce=NONCE,
                             trusted_measurements=[GOOD_MEASUREMENT],
                             trusted_roots=lambda d: False)
    assert res.status == "unverified"
    assert any("trusted-root verification failed" in r for r in res.reasons)


def test_root_verifier_raising_fails_closed():
    doc = parse_attestation(_full_doc())

    def boom(d):
        raise ValueError("boom")

    res = verify_attestation(doc, expected_nonce=NONCE,
                             trusted_measurements=[GOOD_MEASUREMENT],
                             trusted_roots=boom)
    assert res.status == "unverified"           # a broken verifier never passes


# --------------------------------------------------------------------------- #
# convenience block is report-shaped
# --------------------------------------------------------------------------- #

def test_status_for_report_shape():
    block = attestation_status_for_report("none", expected_nonce=NONCE)
    assert set(block) == {"platform", "status", "measurement_matched",
                          "nonce_matched", "reasons"}
    assert block["platform"] == "none" and block["status"] == "none"


# --------------------------------------------------------------------------- #
# Integration with the real ScoringAuthority
# --------------------------------------------------------------------------- #

def _persona_connector(authority, run_id):
    """Strong-but-imperfect connector driven from the server-held keys (test fixture)."""
    _xodex = ROOT.parent / "xodex_omega" / "harness.py"
    spec = importlib.util.spec_from_file_location("xodex_fixture_att", _xodex)
    H = importlib.util.module_from_spec(spec)
    sys.modules["xodex_fixture_att"] = H
    spec.loader.exec_module(H)

    keys = authority.runs[run_id]["answer_keys"]
    order = list(keys.keys())
    answers = {}
    for i, tid in enumerate(order):
        key = keys[tid]
        item = {"grader": key["grader"], "points": key["points"], "negative": key["negative"]}
        answers[tid] = H.synth_bad(item) if (i % 4 == 0) else H.synth_good(item)
    counter = {"i": 0}

    def fn(prompt):
        tid = order[counter["i"]]
        counter["i"] += 1
        time.sleep(0.05)
        return (answers[tid], 0.65)

    return CallableConnector(fn, name="sim-strong-att")


def _run_official(authority, runner, pack, attestation="none"):
    issued = authority.issue_manifest(runner.runner_id, pack, mode="official")
    conn = _persona_connector(authority, issued["manifest"]["run_id"])
    bundle = runner.execute(issued, conn, model_id="demo/strong", attestation=attestation)
    rep = authority.verify_and_score(bundle)
    return issued, bundle, rep


def test_integration_no_attestation_unchanged():
    """Happy path with NO attestation: the new block is 'none' and the existing
    'Verified, non-attested' status is UNCHANGED."""
    authority = ScoringAuthority()
    runner = RunnerAgent()
    runner.register(authority)
    _, _, rep = _run_official(authority, runner, "xodexa-omega", attestation="none")

    assert rep["status"] == "verified"
    assert rep["verification_status"] == "Verified, non-attested"
    assert rep["attestation"] == "none"          # legacy string field untouched
    # new structured block present, defaulting to "none"
    block = rep["attestation_verification"]
    assert block["status"] == "none"
    assert block["platform"] == "none"
    assert block["nonce_matched"] is False


def test_integration_doc_supplied_is_unverified_not_fake_pass():
    """A full quote document bound to the run's nonce, but with no injected vendor-root
    verifier in the authority, must land at 'unverified' — never a fabricated pass."""
    authority = ScoringAuthority()
    runner = RunnerAgent()
    runner.register(authority)

    issued = authority.issue_manifest(runner.runner_id, "xodexa-omega", mode="official")
    run_id = issued["manifest"]["run_id"]
    nonce = issued["manifest"]["nonce"]
    conn = _persona_connector(authority, run_id)
    doc = _full_doc(nonce=nonce)                  # bound to THIS run's nonce
    bundle = runner.execute(issued, conn, model_id="demo/strong", attestation=doc)
    rep = authority.verify_and_score(bundle)

    block = rep["attestation_verification"]
    assert block["platform"] == "nitro"
    assert block["nonce_matched"] is True
    # No trusted-root verifier is wired into the authority -> honest ceiling.
    assert block["status"] == "unverified"
    assert block["status"] != "verified"
    # And it never claims a fake attested-true.
    assert rep["status"] == "verified"           # base verification still stands


# --------------------------------------------------------------------------- #

def _run_standalone():
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  XX  {fn.__name__}  — {e}")
        except Exception as e:  # noqa
            print(f"  XX  {fn.__name__}  — {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(fns)} attestation tests passed")
    return 0 if passed == len(fns) else 1


if __name__ == "__main__":
    print("Xodexa attestation tests\n" + "-" * 40)
    sys.exit(_run_standalone())
