# Security Model

This document describes the threat model and the security architecture of the Xodexa AGI
Benchmark, and is **candid about what cryptography does and does not prove** (per
`ANALYSIS.md` §3.1). Read that section first if you want the full argument; this is the
implementation-accurate summary.

---

## 1. The core trust boundary

The single rule the whole platform is built around:

> **The model provider runs inference. The central authority holds the answer keys and the
> grader, and re-scores from raw outputs. Raw outputs flow inward; answer keys and official
> scores never flow outward.**

| | Central authority (trusted) | Self-hosted runner (untrusted) |
|---|---|---|
| Holds | Server keypair, answer keys, hidden tests | Its own keypair + a model connector |
| Sees model weights | Never | Yes (local) — they never leave the provider |
| Can issue an official score | **Yes — the only issuer** | **No — structurally incapable** |
| Output | Xodexa Verified Score, signed record | Raw outputs + traces + a signed bundle |

The runner is **structurally** incapable of issuing an official score, not merely
policy-forbidden:

- In `official` mode, `authority.issue_manifest` ships **public views only** — graders and
  answers are withheld (`scoring: "central-only"`). The runner has nothing to grade
  against.
- `runner.RunnerAgent` has no scoring authority, no answer keys, and no leaderboard
  credential. Its only "score" is an advisory `local_score`, produced **only** in
  `comparison` mode (where graders are deliberately shipped) and always labelled
  `"Local score — NOT official"`.
- `report.build_report` stamps a note into the verification appendix: official scores are
  issued only by `authority.ScoringAuthority`.

---

## 2. Ed25519 identity and signing

`crypto.py` provides exactly four guarantees and nothing more:

1. **Identity** — `KeyPair` (Ed25519) identifies the central server and each runner.
   `KeyPair.generate()`, `sign(payload)`, module-level `verify(pub_b64, payload, sig)`,
   and `fingerprint(pub_b64)`.
2. **Integrity** — detached signatures over **canonical JSON** (`canonical()` — sorted
   keys, no whitespace, UTF-8) prove a document wasn't altered after signing.
3. **Ordering** — a hash-chained event log makes silent post-hoc edits detectable.
4. **Freshness** — server nonces + timestamps bind a run to a single challenge.

What is signed: the server signs the run manifest and the official record; the runner
signs its result bundle; the dataset pipeline signs each release manifest; the plugin
registry signs plugin manifests.

---

## 3. Hash-chained, tamper-evident logs

`crypto.HashChain` is an append-only log where each entry commits to the previous hash:

```
h_i = SHA256( h_{i-1} || canonical(event_i) )
```

Editing, reordering, inserting, or dropping any event changes `head()` and every hash
after the touched point. `HashChain.verify(entries)` recomputes the chain from the recorded
events and returns `(ok, head_or_error)`, also checking that each entry's `seq` matches its
index. The central authority verifies the chain *and* that the recomputed head matches the
bundle's recorded head.

---

## 4. Server-signed manifests, nonce + replay protection

`authority.issue_manifest` issues a server-signed manifest carrying a fresh `nonce`, a
derived per-run `run_seed` (`sha256(nonce)`), the `task_ids`, the mode, and the server
public key. The runner **verifies the server signature before executing anything**
(`runner.execute` refuses to run on an invalid manifest signature).

On submission, `authority.verify_and_score` enforces hard integrity gates — any failure is
a **reject**:

- `run_known` — the run was issued by this server.
- `not_duplicate` — the run isn't already finalized (replay/duplicate).
- `runner_signature` — Ed25519 signature over the bundle verifies.
- `manifest_binding` — `bundle.manifest_hash == issued manifest hash`.
- `nonce_freshness` — the nonce maps to this run id (no replay across runs).
- `runner_version_allowed` — runner version is in the allowlist.
- `event_log_chain` — the hash chain is intact and the head matches.

The end-to-end demo (`demo/e2e_demo.py`) proves these fail **closed**: editing a response,
editing the event log, or replaying a run are all rejected.

---

## 5. The two score types

| Score | Issued by | Trust |
|---|---|---|
| **Unverified Local Score** | the runner (`comparison` mode only) | advisory; graders were shipped; never official; labelled `"Local score — NOT official"`. |
| **Xodexa Verified Official Score** | the central authority | re-scored centrally from raw outputs against server-held keys. |

The verified score carries a `verification_status` of **"Verified, non-attested"** (the
honest common tier — it trusts the provider didn't look up answers) or **"Verified +
Attested"** when an environment attestation is present (`environment.attestation != "none"`).
The UI must never let "non-attested" masquerade as more than it is.

---

## 6. Contamination defenses

Contamination resistance — not crypto — is the primary integrity mechanism
(`ANALYSIS.md` §1.2). It has a build-time and a run-time half.

### Build-time: similarity filtering (`contamination.CorpusIndex`)

`CorpusIndex` holds a reference corpus we must **not** resemble (public-benchmark items,
crawled web snippets, prior releases). `similarity(text)` returns the best match using the
max of MinHash signature similarity, character-shingle Jaccard, and asymmetric 8-gram
containment; `is_contaminated(text, threshold=0.6)` thresholds it. The pipeline's
contamination stage drops any task at or above the threshold and records the
`public_similarity_score` on every kept task. The MinHash/shingle implementation is the
seam where a real embedding/ANN index (FAISS / pgvector) drops in.

### Run-time: canary echo, timing, suspicious-perfect

Consumed by `authority.verify_and_score` and exposed in `contamination.py`:

- **Canary echo** — every generated task carries a per-task canary token in its prompt.
  If the model's output echoes it, that's a context-dump / training-leak signal
  (`canary_echo_count`; the authority sets the `canary_leakage` penalty).
- **Timing anomaly** — answers faster than `MIN_PLAUSIBLE_MS_PER_TASK` (40 ms) suggest
  cached/looked-up answers (`timing_anomaly_fraction`; penalized when >50% of tasks are
  implausibly fast).
- **Suspicious perfect score** — a fraction `>= 0.97` is flagged
  (`suspicious_perfect`; sets `contamination_risk`).

Any of these flags moves the run's status to **flagged** and feeds a bounded external
penalty into the Xodexa Score.

---

## 7. The trust boundary on disk

The dataset build writes hidden answer keys to a separate directory:

- Public/validation packs: answer keys ship to the release directory under `datasets/`.
- The hidden official set: public views ship to `datasets/`, but answer keys are written
  to **`server_keys/`**, which is **git-ignored** (`.gitignore` line `server_keys/`).

This embodies the trust boundary in the repository layout: the hidden answer keys are
never committed, never shipped, and only ever exist server-side.

---

## 8. What the crypto does NOT prove (be honest)

Cryptography proves **identity** (who produced a bundle), **integrity** (unaltered after
signing), **ordering** (the log wasn't silently edited), and **freshness** (no replay). It
does **not** prove:

- **which model actually ran**, nor
- **that the provider didn't look up answers during inference**.

A hash-chained log only proves a log wasn't edited *after the fact* — not that it was
truthful when written. The defenses that actually close those gaps, in order:

1. **The runner never gets answer keys or hidden tests.** Central re-scoring from raw
   outputs is the non-optional default for official scores.
2. **Contamination resistance is the real moat** — per-run generated variants, private
   hidden sets with rotation, canaries, and central hidden-test execution.
3. **Remote attestation** (SEV-SNP / TDX / Nitro / CVM) is the only thing that upgrades
   "we trust the provider's honesty" to "we trust the silicon" — and most labs won't run
   it, so *Verified, non-attested* is the honest common tier.

**No self-hosted benchmark can be made perfectly cheat-proof** unless execution, hidden
tests, and scoring are centrally controlled or remotely attested. Xodexa **reduces — not
eliminates —** cheating risk, and says so.
