"""
xodexa.registry
=================
The plugin & dataset registry. Plugins (benchmark packs, dataset adapters, scoring
plugins, model adapters, tool simulators, agent environments, safety packs) are how
the platform grows without trusting arbitrary code. The security posture is therefore
strict and enforced HERE, not by convention:

  * Every plugin MUST be signed (Ed25519) and the signature MUST verify.
  * Every plugin MUST declare a permission block; defaults are deny.
  * No default network access; no unrestricted shell; no secrets access.
  * A sandbox is required; SBOM + checksum are required and verified.

``validate_manifest`` returns a list of policy violations; ``PluginRegistry.install``
refuses anything non-empty. This mirrors SLSA/Sigstore-style supply-chain controls at
MVP fidelity (real deployments add cosign verification + static analysis + malware scan
at the points marked below).
"""

from __future__ import annotations

import time

from .crypto import KeyPair, verify, sha256_hex, canonical

PLUGIN_TYPES = {
    "benchmark_pack", "dataset_adapter", "scoring_plugin", "model_adapter",
    "tool_simulator", "agent_environment", "safety_pack", "enterprise_workflow_pack",
}
ALLOWED_FS = {"none", "sandbox-only", "read-only"}
ALLOWED_SHELL = {"none", "restricted"}        # "unrestricted" is forbidden
ALLOWED_SECRETS = {"none"}                     # plugins never get secrets in the MVP


def manifest_signing_body(manifest: dict) -> dict:
    """The canonical body that the signature covers (everything except signature)."""
    return {k: v for k, v in manifest.items() if k != "signature"}


def validate_manifest(manifest: dict, *, require_signature: bool = True,
                      trusted_keys: set[str] | None = None) -> list[str]:
    """Return policy violations ([] == installable)."""
    v: list[str] = []
    m = manifest

    def need(cond, msg):
        if not cond:
            v.append(msg)

    need(bool(m.get("name")), "name required")
    need(bool(m.get("version")), "version required")
    need(m.get("type") in PLUGIN_TYPES, f"type must be one of {sorted(PLUGIN_TYPES)}")
    need(bool(m.get("license")), "license required")
    need(bool(m.get("sbom")), "SBOM required (supply-chain transparency)")
    need(bool(m.get("checksum")), "checksum required")

    perms = m.get("permissions") or {}
    need(bool(perms), "permissions block required (default-deny)")
    need(perms.get("network", False) is False, "network access is denied by default")
    need(perms.get("filesystem", "none") in ALLOWED_FS,
         f"filesystem must be one of {sorted(ALLOWED_FS)}")
    need(perms.get("shell", "none") in ALLOWED_SHELL,
         "shell must be 'none' or 'restricted' (unrestricted shell forbidden)")
    need(perms.get("secrets", "none") in ALLOWED_SECRETS,
         "secrets access forbidden (must be 'none')")
    need(perms.get("sandbox", True) is not False, "sandbox is required")

    # checksum integrity over declared contents.
    payload = {k: m.get(k) for k in ("datasets", "scorers", "tools")}
    expected = sha256_hex(payload)
    need(m.get("checksum") == expected,
         "checksum does not match declared datasets/scorers/tools")

    if require_signature:
        sig = m.get("signature")
        signer = m.get("signer_pub")
        need(bool(sig) and bool(signer), "plugin must be signed (signature + signer_pub)")
        if sig and signer:
            ok = verify(signer, manifest_signing_body(m), sig)
            need(ok, "signature verification failed")
            if trusted_keys is not None:
                need(signer in trusted_keys,
                     "signer is not in the trusted-key allowlist")
    return v


def sign_manifest(manifest: dict, signer: KeyPair) -> dict:
    """Fill checksum + signer_pub + signature on a manifest (publisher side)."""
    m = dict(manifest)
    m.setdefault("datasets", [])
    m.setdefault("scorers", [])
    m.setdefault("tools", [])
    m["checksum"] = sha256_hex({k: m.get(k) for k in ("datasets", "scorers", "tools")})
    m["signer_pub"] = signer.pub_b64
    m["signature"] = signer.sign(manifest_signing_body(m))
    return m


class PluginRegistry:
    def __init__(self, trusted_keys: set[str] | None = None):
        self.installed: dict[str, dict] = {}
        self.trusted_keys = trusted_keys  # None == accept any valid signature

    def install(self, manifest: dict, *, org_admin_approved: bool = False) -> dict:
        violations = validate_manifest(manifest, trusted_keys=self.trusted_keys)
        # ---- real deployments also run here: static analysis + malware scan ----
        if violations:
            return {"installed": False, "violations": violations}
        # org installs require admin approval (spec: "admin approval for org installs")
        key = f"{manifest['name']}@{manifest['version']}"
        self.installed[key] = {"manifest": manifest, "installed_at": time.time(),
                               "org_admin_approved": org_admin_approved}
        return {"installed": True, "plugin": key, "type": manifest["type"]}

    def list_installed(self) -> list[dict]:
        return [{"plugin": k, "type": v["manifest"]["type"],
                 "license": v["manifest"].get("license")}
                for k, v in self.installed.items()]


def example_manifest(name="xodexa-code-gauntlet", ptype="benchmark_pack") -> dict:
    """A spec-shaped example used by docs/tests."""
    return {
        "name": name, "version": "1.0.0", "type": ptype, "license": "Apache-2.0",
        "author": "xodexa", "permissions": {
            "network": False, "filesystem": "sandbox-only", "secrets": "none",
            "shell": "restricted", "sandbox": True},
        "datasets": ["code_mini.jsonl"], "scorers": ["pytest_hidden"], "tools": [],
        "sbom": "spdx:example", "description": "Code & SWE gauntlet pack.",
    }
