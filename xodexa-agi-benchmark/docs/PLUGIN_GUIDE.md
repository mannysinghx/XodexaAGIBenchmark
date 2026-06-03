# Plugin Guide

Plugins are how the platform grows — new benchmark packs, dataset adapters, scorers, model
adapters, tool simulators, agent environments, safety packs — **without trusting arbitrary
code**. The security posture is strict and **enforced in `registry.py`**, not by
convention.

---

## 1. Plugin types

`registry.PLUGIN_TYPES`:

- `benchmark_pack`
- `dataset_adapter`
- `scoring_plugin`
- `model_adapter`
- `tool_simulator`
- `agent_environment`
- `safety_pack`
- `enterprise_workflow_pack`

---

## 2. The plugin manifest schema

A manifest is a dict. The fields the registry reads/validates:

| Field | Required | Notes |
|---|---|---|
| `name` | yes | Plugin name. |
| `version` | yes | Used in the install key `name@version`. |
| `type` | yes | One of `PLUGIN_TYPES`. |
| `license` | yes | SPDX or text. |
| `sbom` | yes | Software Bill of Materials — supply-chain transparency. |
| `checksum` | yes | SHA-256 over the declared `datasets`/`scorers`/`tools` (filled by `sign_manifest`). |
| `permissions` | yes | Default-deny block (see below). |
| `datasets`, `scorers`, `tools` | — | Declared contents the checksum covers. |
| `signer_pub`, `signature` | yes (to install) | Ed25519 public key + signature over the manifest body. |
| `author`, `description` | optional | Metadata. |

---

## 3. The enforced security policy

`registry.validate_manifest(manifest, require_signature=True, trusted_keys=None)` returns a
list of policy violations (`[]` means installable). It enforces:

- **Must be signed.** `signature` + `signer_pub` are required and the signature must verify
  over the manifest body (everything except `signature`). If a `trusted_keys` allowlist is
  supplied, the signer must be in it.
- **Default-deny permissions.** A `permissions` block is required, and:
  - `network` must be `False` (`ALLOWED_FS`-style hard default-deny).
  - `filesystem` must be one of `none` / `sandbox-only` / `read-only` (`ALLOWED_FS`).
  - `shell` must be `none` or `restricted` — `unrestricted` is forbidden (`ALLOWED_SHELL`).
  - `secrets` must be `none` — plugins never get secrets in the MVP (`ALLOWED_SECRETS`).
  - `sandbox` must not be `False` — a sandbox is required.
- **SBOM + checksum required**, and the checksum must match `sha256_hex` over the declared
  `datasets`/`scorers`/`tools`.

`PluginRegistry.install(manifest, org_admin_approved=False)` refuses any manifest with
non-empty violations, and records `org_admin_approved` so **org installs require admin
approval**. (Real deployments also run static analysis + a malware scan at the marked
point in `install`.)

```python
ALLOWED_FS      = {"none", "sandbox-only", "read-only"}
ALLOWED_SHELL   = {"none", "restricted"}   # "unrestricted" forbidden
ALLOWED_SECRETS = {"none"}                  # plugins never get secrets
```

---

## 4. Worked example: sign and install

```python
from xodexa import registry
from xodexa.crypto import KeyPair

# 1. Build a manifest (default-deny permissions are mandatory).
manifest = {
    "name": "xodexa-code-gauntlet",
    "version": "1.0.0",
    "type": "benchmark_pack",
    "license": "Apache-2.0",
    "author": "xodexa",
    "permissions": {
        "network": False,
        "filesystem": "sandbox-only",
        "secrets": "none",
        "shell": "restricted",
        "sandbox": True,
    },
    "datasets": ["code_mini.jsonl"],
    "scorers": ["pytest_hidden"],
    "tools": [],
    "sbom": "spdx:example",
    "description": "Code & SWE gauntlet pack.",
}

# 2. Sign it (publisher side). This fills checksum + signer_pub + signature.
publisher = KeyPair.generate()
signed = registry.sign_manifest(manifest, publisher)

# 3. Validate (registry side). [] means installable.
violations = registry.validate_manifest(signed)
assert violations == [], violations

# 4. Install. trusted_keys=None accepts any valid signature; pass a set to allowlist.
reg = registry.PluginRegistry(trusted_keys={publisher.pub_b64})
result = reg.install(signed, org_admin_approved=True)
# -> {"installed": True, "plugin": "xodexa-code-gauntlet@1.0.0", "type": "benchmark_pack"}

reg.list_installed()
# -> [{"plugin": "xodexa-code-gauntlet@1.0.0", "type": "benchmark_pack", "license": "Apache-2.0"}]
```

If the manifest is unsigned, requests network access, asks for secrets, or its checksum
doesn't match its declared contents, `install` returns
`{"installed": False, "violations": [...]}` with the exact reasons.

`registry.example_manifest(name=..., ptype=...)` returns a spec-shaped example used by docs
and tests.

---

## 5. Notes

- The signature covers `manifest_signing_body(manifest)` — the whole manifest except the
  `signature` field — so changing any field after signing invalidates it.
- The checksum is computed over only `{"datasets", "scorers", "tools"}`, so those declared
  contents are tamper-evident against the manifest.
- This mirrors SLSA / Sigstore-style supply-chain controls at MVP fidelity. The full
  marketplace with cosign verification, static analysis, and malware scanning is a roadmap
  item; the policy gates above are real and enforced today.

See [SECURITY_MODEL.md](./SECURITY_MODEL.md) for the platform-wide trust boundary that this
plugin policy sits inside.
