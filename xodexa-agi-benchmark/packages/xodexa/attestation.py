"""
xodexa.attestation
=====================
Hardware-attestation VERIFICATION INTERFACE for the Xodexa AGI Benchmark.

Why this module exists (and why it is deliberately honest about its limits):

The platform's trust model (docs/METHODOLOGY.md, docs/SECURITY_MODEL.md) is candid
that a "Verified" score WITHOUT hardware attestation only proves the runner's key
signed the raw outputs and that the hash-chained log is intact — it does NOT prove
the provider actually ran the named model in an isolated environment, nor that it
refrained from looking answers up. Confidential-computing attestation (AWS Nitro
Enclaves, AMD SEV-SNP, Intel TDX) is the roadmap upgrade that would remove that
residual trust: the enclave measures its own code/config into a signed quote bound
to a fresh nonce, so a verifier can cryptographically pin *what* ran.

Real enclave attestation requires validating a quote against the platform vendor's
root certificates on genuine hardware we do not have in this environment. So this
module builds the honest HALF we CAN build correctly today:

  * a tolerant PARSER for attestation documents,
  * STRUCTURAL verification (nonce binding to this run, measurement allow-listing,
    presence of signature + cert chain),
  * a clear, report-ready STATUS that DEFAULTS to "none"/"unverified" and never
    fabricates an "attested: true".

The one thing this module refuses to do is *pretend*. Actual vendor cert-chain
validation is injected via a `RootVerifier` callback that a real deployment supplies
(wired to Nitro/SEV-SNP/TDX libraries). Absent that verifier, the most a structurally
valid document can earn is "unverified" — with a reason explaining exactly why. That
keeps the honest default intact: no root verifier => never a real pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, Sequence, Union, runtime_checkable

# Platforms we recognize. "none" is the honest default — no attestation supplied.
KNOWN_PLATFORMS = ("nitro", "sev_snp", "tdx", "none")


# --------------------------------------------------------------------------- #
# Attestation document
# --------------------------------------------------------------------------- #

@dataclass
class AttestationDoc:
    """
    A parsed, structurally-normalized attestation document.

    Fields mirror the shape shared across confidential-computing platforms:
      * platform    — which enclave technology produced the quote.
      * measurement — the code/config measurement (Nitro PCRs digest, SEV-SNP launch
                      measurement, TDX MRTD/RTMR). Verifiers compare this against a set
                      of TRUSTED measurements to pin exactly what ran.
      * nonce       — the challenge the quote is bound to; MUST equal the run's nonce
                      so an attestation cannot be replayed onto a different run.
      * signature   — the enclave/quote signature (opaque here; validated by the
                      injected RootVerifier against vendor roots in a real deployment).
      * cert_chain  — the certificate chain from the signing key up toward the vendor
                      root (again, only structurally inspected here).
      * raw         — the original object as supplied, retained for auditability.
    """
    platform: str = "none"
    measurement: str = ""
    nonce: str = ""
    signature: str = ""
    cert_chain: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def is_present(self) -> bool:
        """True when a real (non-"none") platform was claimed."""
        return self.platform in KNOWN_PLATFORMS and self.platform != "none"

    @property
    def has_structure(self) -> bool:
        """True when the document carries the crypto material a real quote would have."""
        return bool(self.signature) and bool(self.cert_chain)


def parse_attestation(obj: Union[dict, str, None]) -> AttestationDoc:
    """
    Tolerant parse of whatever the runner stamped into environment.attestation.

    Accepts:
      * a full dict document {"platform","measurement","nonce","signature",
        "cert_chain",...},
      * a bare string (e.g. "nitro" or "none") — the legacy field shape, treated as a
        platform name with no crypto material,
      * None / anything unrecognized -> platform "none".

    Unknown or missing platforms collapse to "none". This never raises: a malformed
    document simply yields a "none"/empty doc, so callers can rely on getting an
    AttestationDoc back and letting `verify_attestation` decide the status.
    """
    if obj is None:
        return AttestationDoc(platform="none", raw={})

    # Legacy shape: the field is just a platform string ("none", "nitro", ...).
    if isinstance(obj, str):
        platform = obj.strip().lower()
        if platform not in KNOWN_PLATFORMS:
            platform = "none"
        return AttestationDoc(platform=platform, raw={"platform": obj})

    if not isinstance(obj, dict):
        return AttestationDoc(platform="none", raw={})

    platform = str(obj.get("platform", "none")).strip().lower()
    if platform not in KNOWN_PLATFORMS:
        platform = "none"

    cert_chain = obj.get("cert_chain", [])
    if isinstance(cert_chain, str):
        cert_chain = [cert_chain]
    elif isinstance(cert_chain, (list, tuple)):
        cert_chain = [str(c) for c in cert_chain]
    else:
        cert_chain = []

    return AttestationDoc(
        platform=platform,
        measurement=str(obj.get("measurement", "") or ""),
        nonce=str(obj.get("nonce", "") or ""),
        signature=str(obj.get("signature", "") or ""),
        cert_chain=cert_chain,
        raw=dict(obj),
    )


# --------------------------------------------------------------------------- #
# Pluggable vendor root verification
# --------------------------------------------------------------------------- #

@runtime_checkable
class RootVerifier(Protocol):
    """
    Injection point for REAL vendor cert-chain validation.

    A production deployment supplies an implementation that validates `doc.signature`
    and `doc.cert_chain` up to the platform vendor's trusted root (AWS Nitro, AMD
    SEV-SNP, Intel TDX) and returns True only if the quote is genuine. This module
    intentionally does NOT ship such a validator — doing so with placeholder roots
    would be security theatre. It returns True/False for a given document.
    """

    def __call__(self, doc: "AttestationDoc") -> bool:  # pragma: no cover - protocol
        ...


# A plain callable is accepted anywhere a RootVerifier is expected.
RootVerifierFn = Callable[["AttestationDoc"], bool]


# --------------------------------------------------------------------------- #
# Verification result
# --------------------------------------------------------------------------- #

@dataclass
class VerificationResult:
    """
    Outcome of verifying an attestation document against a run.

    status:
      * "none"       — no attestation supplied (the DEFAULT). Not an error.
      * "unverified" — a document was supplied and passed structural/nonce/measurement
                       checks, but genuine vendor cert-chain validation was NOT done
                       (no RootVerifier configured, or the verifier declined). This is
                       the honest ceiling without real hardware roots.
      * "invalid"    — a document was supplied but FAILED a binding check (nonce
                       mismatch, missing structure). It must not be trusted.
      * "verified"   — a RootVerifier confirmed the quote AND every structural check
                       passed. Only reachable with an injected verifier.
    """
    status: str = "none"
    platform: str = "none"
    reasons: list[str] = field(default_factory=list)
    measurement_matched: bool = False
    nonce_matched: bool = False

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "status": self.status,
            "measurement_matched": self.measurement_matched,
            "nonce_matched": self.nonce_matched,
            "reasons": list(self.reasons),
        }


# --------------------------------------------------------------------------- #
# Verification logic
# --------------------------------------------------------------------------- #

def verify_attestation(
    doc: AttestationDoc,
    expected_nonce: Optional[str],
    trusted_measurements: Optional[Sequence[str]] = None,
    trusted_roots: Optional[RootVerifierFn] = None,
) -> VerificationResult:
    """
    Structurally verify an attestation document and classify its trust status.

    The logic is deliberately conservative so the honest default holds:

      1. platform "none"/missing  -> status "none". No attestation was supplied; this
         is the normal, expected state and is NOT treated as a failure.
      2. nonce binding            -> doc.nonce MUST equal `expected_nonce` (the run's
         nonce). A mismatch (or an empty nonce) means the quote is not bound to THIS
         run: reason "nonce mismatch", status "invalid". This gate runs first because
         an unbound quote is worthless regardless of anything else.
      3. structure                -> a real quote carries a signature and a cert chain.
         Missing either -> reason "missing signature/cert_chain structure", status
         "invalid".
      4. measurement allow-list   -> if `trusted_measurements` is supplied, doc.measurement
         MUST be in it; otherwise reason "unknown measurement" and measurement_matched
         stays False. With no allow-list supplied we cannot vouch for the measurement,
         so measurement_matched is left False and a note is recorded.
      5. vendor root validation   -> ONLY when nonce is bound, structure is present, and
         (if an allow-list was given) the measurement is trusted do we consider a pass.
         Even then, a genuine "verified" requires an injected `trusted_roots` verifier
         returning True — because real enclave cert validation needs platform vendor
         roots this module does not (and must not pretend to) have. Without a verifier
         the result is "unverified" with the explanatory reason. A verifier that
         returns False also yields "unverified".

    Returns a VerificationResult; never raises on well-formed inputs.
    """
    reasons: list[str] = []

    # (1) No attestation supplied -> the honest default. Not an error.
    if doc is None or not doc.is_present:
        return VerificationResult(
            status="none",
            platform=(doc.platform if doc is not None else "none"),
            reasons=["no attestation supplied"],
            measurement_matched=False,
            nonce_matched=False,
        )

    platform = doc.platform

    # (2) Nonce binding — an attestation not bound to THIS run is worthless.
    nonce_matched = bool(expected_nonce) and doc.nonce == expected_nonce
    if not nonce_matched:
        reasons.append("nonce mismatch")
        return VerificationResult(
            status="invalid",
            platform=platform,
            reasons=reasons,
            measurement_matched=False,
            nonce_matched=False,
        )

    # (3) Structural presence of the crypto material a real quote would carry.
    if not doc.has_structure:
        reasons.append("missing signature/cert_chain structure")
        return VerificationResult(
            status="invalid",
            platform=platform,
            reasons=reasons,
            measurement_matched=False,
            nonce_matched=nonce_matched,
        )

    # (4) Measurement allow-list (pin exactly what code/config ran).
    if trusted_measurements is not None:
        measurement_matched = doc.measurement in set(trusted_measurements)
        if not measurement_matched:
            reasons.append("unknown measurement")
    else:
        # No allow-list to check against -> we cannot vouch for the measurement.
        measurement_matched = False
        reasons.append("no trusted-measurement set supplied")

    # If the measurement was required but not trusted, we stop at "unverified":
    # structure and nonce are fine, but we will not vouch for unknown code.
    if trusted_measurements is not None and not measurement_matched:
        return VerificationResult(
            status="unverified",
            platform=platform,
            reasons=reasons,
            measurement_matched=measurement_matched,
            nonce_matched=nonce_matched,
        )

    # (5) Vendor root validation — the ONLY path to a genuine "verified".
    if trusted_roots is None:
        reasons.append(
            "no trusted-root verifier configured "
            "(real enclave cert validation requires platform vendor roots)"
        )
        return VerificationResult(
            status="unverified",
            platform=platform,
            reasons=reasons,
            measurement_matched=measurement_matched,
            nonce_matched=nonce_matched,
        )

    try:
        root_ok = bool(trusted_roots(doc))
    except Exception as exc:  # a broken verifier must fail closed, never pass.
        reasons.append(f"trusted-root verifier error: {type(exc).__name__}")
        root_ok = False

    if not root_ok:
        reasons.append("trusted-root verification failed")
        return VerificationResult(
            status="unverified",
            platform=platform,
            reasons=reasons,
            measurement_matched=measurement_matched,
            nonce_matched=nonce_matched,
        )

    # Everything checked out AND a real verifier vouched for the vendor chain.
    return VerificationResult(
        status="verified",
        platform=platform,
        reasons=reasons or ["attestation verified against trusted root"],
        measurement_matched=measurement_matched,
        nonce_matched=nonce_matched,
    )


# --------------------------------------------------------------------------- #
# Report-ready convenience
# --------------------------------------------------------------------------- #

def attestation_status_for_report(
    doc_or_obj: Union[AttestationDoc, dict, str, None],
    expected_nonce: Optional[str],
    trusted_measurements: Optional[Sequence[str]] = None,
    trusted_roots: Optional[RootVerifierFn] = None,
) -> dict:
    """
    Parse (if needed) + verify + return a report-ready block:

        {"platform", "status", "measurement_matched", "nonce_matched", "reasons"}

    Accepts a raw document/string (parsed tolerantly) or an already-parsed
    AttestationDoc. Designed to be dropped straight into a run report under a key such
    as report["attestation_verification"]. Defaults to status "none" when nothing was
    supplied — never a fabricated pass.
    """
    doc = doc_or_obj if isinstance(doc_or_obj, AttestationDoc) else parse_attestation(doc_or_obj)
    result = verify_attestation(
        doc,
        expected_nonce=expected_nonce,
        trusted_measurements=trusted_measurements,
        trusted_roots=trusted_roots,
    )
    return result.to_dict()
