# Xodexa AGI Benchmark — Critical Analysis & Improved Architecture

*A candid engineering review of the original specification, the central design
problem it must solve, and the build order that actually produces working
infrastructure instead of a beautiful diagram.*

---

## 1. The verdict up front

The specification is ambitious, mostly coherent, and asks for the right things in
the right categories. Its weakness is not vision — it's **scope discipline** and one
**unsolved core problem** that the spec correctly names but does not actually solve.
If you build it top-to-bottom as written you will produce ~150 half-working
components and zero trustworthy scores. If you build it in the order below you get a
small thing that is *actually trustworthy* first, and grow it.

Two things matter more than everything else on the list combined:

1. **The trust boundary.** A self-hosted runner that the model provider controls can
   never be trusted to *score* anything. The only defensible architecture is: the
   provider runs *inference*, the central app holds the *answer keys and the grader*
   and re-scores from raw outputs. The spec gestures at this ("re-score results
   centrally") but then also lists a "Local Score" path and a pile of cryptographic
   theater that does **not** close the gap. Crypto proves *who* produced a bundle and
   that it *wasn't altered in transit* — it proves nothing about whether the model
   actually produced those outputs, or whether the provider's machine looked up the
   answer. Be honest about this (the spec's "Critical honesty" section is the most
   important paragraph in the whole document) and design around it.

2. **Contamination resistance is a data strategy, not a feature.** The hardest
   benchmark on Earth is worthless the week after its questions leak into a training
   set. Everything about "hidden tasks," "per-run variants," and "private set
   rotation" is the actual moat. This must be a first-class subsystem, not an
   afterthought bolted onto a leaderboard.

The MVP we build proves both of these end-to-end on a small scale, using the
existing Xodexa-Ω gauntlet as the first benchmark pack.

---

## 2. What the spec gets right (keep as-is)

- **Two-part architecture** (central authority + open runner). Correct and necessary.
- **Local vs. Verified vs. Verified+Attested score tiers.** Exactly the right way to
  be honest with users about trust level. This is the product's integrity story.
- **Adapter-first interoperability** (HELM / lm-eval-harness / Inspect AI /
  OpenCompass / OpenAI Evals). Do not rebuild these. Wrapping them is the single
  highest-leverage decision in the plan.
- **Three-layer data strategy** (public / generated / private-hidden). This is the
  correct contamination defense. Layer 2 (procedural generation) is underrated and
  should be pushed *harder* — generated tasks are the only ones that are truly
  un-leakable.
- **Penalty-driven scoring** (hallucination, overconfidence, unsafe compliance). This
  is what makes a benchmark "unforgiving" and is exactly the philosophy already proven
  in Xodexa-Ω. Keep it central.
- **Sandboxed, simulated tools** for agentic tasks. Correct — never touch real
  systems in official runs.

---

## 3. What is wrong, weak, or over-built

### 3.1 The cryptography is necessary but **oversold**
The spec implies that signing + hash chains + Cosign + SLSA + in-toto + enclaves
make scores cheat-proof. They do not. Ranked by what each actually buys you:

| Mechanism | What it actually prevents | What it does **not** prevent |
|---|---|---|
| Runner keypair + signed bundle | Forged submissions, MITM tampering | Provider lying about which model ran, or precomputing answers |
| Hash-chained event log | Post-hoc edits to the log | A log that was fraudulent when written |
| Server-held answer keys + central re-scoring | Runner grading itself; most answer leakage | A provider that looked up answers *during* inference |
| Per-run task variants + canaries | Static answer caches; detects training-set leakage | A model genuinely strong on that variant |
| **Remote attestation (SEV-SNP/TDX/Nitro)** | Running a different model/build than declared | Side-channel exotica; still trusts the CPU vendor |
| Central hidden-test execution | Almost everything above, for testable tasks | Tasks that can't be re-graded server-side |

**Improvement:** make the *trust ladder* explicit and make central re-scoring the
default, not an option. The single most important rule, stated plainly in product and
docs: **the runner never receives answer keys or hidden tests; it only ever returns
raw model outputs and traces.** Attestation is the only thing that upgrades "we
trust the provider's honesty" to "we trust the silicon," and most labs won't run it —
so the *common* official tier is "Verified, non-attested," and the UI must never let
that masquerade as more than it is.

### 3.2 The technology list is a kitchen sink
Keycloak **and** Ory; Celery **and** RQ **and** Temporal; Recharts **and** ECharts;
FastAPI **or** NestJS; ClickHouse + Prometheus + Grafana + Loki + OpenTelemetry +
OpenBao + OPA + Gatekeeper + Cosign + SLSA + in-toto + 5 confidential-computing
vendors — on day one. This is how MVPs die.

**Improvement — opinionated stack, defer the rest behind interfaces:**

| Concern | MVP choice | Deferred (interface now, swap later) |
|---|---|---|
| API | **FastAPI** (Python — same language as the eval engine; kills the polyglot tax) | — |
| Queue | **Redis + RQ** | Temporal only when long-horizon agent runs need durable workflows |
| DB | **Postgres** | ClickHouse only when event volume justifies an OLAP store |
| Auth | **Ory Kratos/Hydra** *or* just JWT for MVP | Keycloak if an org demands it |
| Object store | **MinIO** | — |
| Signing | **Sigstore/Cosign** for images; **Ed25519** for runner/bundle/manifest | in-toto/SLSA provenance at GA |
| Observability | **OpenTelemetry → one backend** | full Prom/Grafana/Loki at scale |
| Charts | **ECharts** (radar/heatmap-heavy UI needs its power) | — |

Pick one of each. Every "X or Y" in the original spec is a decision deferred onto
future-you at the worst possible time.

### 3.3 The Xodexa Score formula is under-specified and will be gamed
"weighted capability + bonuses − penalties" with nine weighted categories looks
rigorous but hides three problems: (a) **missing-category handling** — almost no model
will run all nine gauntlets; how do you score partial coverage without making
selective submission a strategy? (b) **penalty unit mismatch** — penalties and the
capability score must live on the same scale or one swamps the other. (c) **no
confidence interval** — a single 0–1000 integer invites spurious precision.

**Improvements:**
- Xodexa Score is computed **only over evaluated categories**, and the leaderboard
  shows a **coverage %**. A model that ran 3 of 9 gauntlets gets a score *plus* a
  "Partial (3/9)" badge and is ranked in a separate bucket. No more cherry-picking.
- Penalties are expressed as **fractions of the category they attack** (a
  hallucination penalty reduces the truthfulness sub-score), bounded, so no single
  penalty can drive the total negative absurdly — but a model that hallucinates
  constantly still craters, exactly as intended.
- Report a **bootstrap 95% CI** on the score and show it on the leaderboard. "742 ±
  18" is honest; "742" is not.

### 3.4 "Difficulty: 9.8" is a number with no definition
Hand-assigned difficulty floats are meaningless. **Improvement:** difficulty is
**empirical** — derived from the human-baseline pass rate and the frontier-model pass
rate, recomputed as data arrives (cf. IRT / item-response theory). A task only earns
a high difficulty rating by *actually* defeating strong models.

### 3.5 Safety testing as specified is a liability
"Jailbreak resistance," "deception simulation," "data exfiltration resistance" run on
your infrastructure means you are hosting and serving attack content. **Improvement:**
keep the spec's instinct ("safe abstract tasks," "harmful prompts abstracted") but
make it a hard rule: the safety gauntlet tests *behavioral properties* (does the model
follow the instruction hierarchy, resist prompt injection embedded in tool output,
refuse appropriately without over-refusing) using **abstracted, non-operational**
scenarios. No runnable exploit content, ever. This also keeps the project hostable.

### 3.6 Things to cut from the MVP entirely (build later)
Enclave attestation across five vendors; the full plugin marketplace with malware
scanning; Temporal; ClickHouse; human-review workflow; mTLS; OPA/Gatekeeper; the
private-enterprise multi-tenant isolation layer. Every one is real and belongs on the
roadmap — none is needed to prove the platform's core claim is true.

---

## 4. The corrected architecture (one diagram in words)

```
   MODEL PROVIDER'S INFRASTRUCTURE                 APEXAGI CENTRAL (trusted)
 ┌───────────────────────────────────┐         ┌────────────────────────────────┐
 │  xodexa-runner (open source)      │         │  Main App / Scoring Authority   │
 │                                    │         │                                 │
 │  • holds RUNNER private key        │  (1)reg │  • holds SERVER private key     │
 │  • model connector (vLLM/Ollama/…) │ ───────▶│  • holds ANSWER KEYS (never     │
 │  • runs INFERENCE only             │         │    leave this boundary)         │
 │  • builds hash-chained event log   │ ◀───────│  • issues signed manifest+nonce │
 │  • signs result bundle             │  (2)mfst│  • generates per-run variants   │
 │  • submits RAW OUTPUTS + traces    │         │                                 │
 │                                    │ ────────▶  (3) verify sig + chain + nonce │
 │  produces: LOCAL score (advisory)  │  submit │  (4) RE-SCORE from raw outputs  │
 └───────────────────────────────────┘         │  (5) canary/contamination/timing│
            ▲ never sees answers               │  (6) penalties → Xodexa Score      │
            │ never writes leaderboard         │  (7) status: verified/flag/reject│
            └───────────────────────────────  │  (8) publish (signed record)    │
                                                └────────────────────────────────┘
```

The invariant that makes the whole thing defensible:
**raw outputs flow inward; answers and official scores never flow outward.**

---

## 5. Prioritized build order (what "done" means at each step)

**Phase 0 — Trust kernel (this MVP).**
Ed25519 keypairs for server + runner; signed run manifest with server nonce;
per-run task variant generation; runner executes inference + hash-chained log + signs
bundle; central verification (signature, manifest hash, nonce/replay, chain integrity)
+ central re-scoring with server-held keys; canary, perfect-score, and timing-anomaly
checks; Xodexa Score with penalties + coverage + CI; Local vs Verified labeling; a
tamper test that *proves* a modified bundle is rejected. **Engine = Xodexa-Ω.** Done =
the e2e demo runs and the tamper test fails closed.

**Phase 1 — Platform skeleton.** FastAPI service exposing the kernel over REST +
the Postgres schema + OpenAPI + docker-compose + a real leaderboard read API.

**Phase 2 — Adapters.** lm-eval-harness and Inspect AI adapters first (widest reach),
then HELM/OpenCompass/OpenAI-Evals import-export. Each adapter only ever feeds *raw
outputs* into central scoring.

**Phase 3 — Data engine.** Push Layer-2 procedural generation hard (it's the only
un-leakable layer); wire the public Layer-1 packs (MMLU-Pro, GPQA-Diamond,
SWE-bench-Verified, LiveCodeBench, BigCodeBench, GAIA, tau-bench) as *comparison-only*;
stand up Layer-3 private rotation + canary leak detection.

**Phase 4 — Agentic + sandbox tools.** Simulated, deterministic, replayable tools in
hardened sandboxes. This is where SWE-bench/tau-bench/GAIA become real.

**Phase 5 — Hardening & trust upgrades.** Cosign/SLSA/in-toto provenance; optional
attestation (Nitro first — easiest managed path); plugin marketplace with signing +
static analysis; multi-tenant private-eval isolation; human review for top entries.

**Phase 6 — Frontend depth.** The dark research-lab UI, radar/heatmap/failure-matrix
views, compare, reports. (A static demo ships in the MVP to lock the aesthetic.)

---

## 6. Concrete corrections folded into this build

- Runner is structurally incapable of writing a leaderboard score (no code path, no
  credential scope) — enforced, not just policy.
- The answer keys live only in the central engine; the runner's task bundle is
  prompts-only. Long-context/generated tasks are expanded **server-side per run** from
  the nonce, so the variant a runner sees is unique and its key is retained centrally.
- Every official score carries: `verification_status`, `attestation`, `coverage`,
  `score ± CI`, and the list of checks that passed/failed. No bare numbers.
- "Verified, non-attested" is the honest default and is visually distinct from
  "Verified + Attested." Neither is "Local."
- Threat model is documented in the README, including the explicit statement that
  without attestation the platform trusts the provider not to have looked up answers,
  and that contamination defense — not crypto — is the primary integrity mechanism.

---

*This analysis is the contract for the code in this repository: the MVP implements
Phase 0 against Xodexa-Ω, scaffolds Phase 1, and documents Phases 2–6 as the roadmap.*
