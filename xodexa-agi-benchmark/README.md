<div align="center">

# Xodexa AGI Benchmark

### Built to break the best.

**The world's most unforgiving open benchmark for frontier AI — we don't rank models, we measure how far they fall short of AGI.**

*Open-source-first · self-hostable · cryptographically verified central scoring*

</div>

---

Xodexa AGI Benchmark is a two-part platform for evaluating frontier and AGI-level systems on
capability that **cannot be faked by memorization**: adversarial reasoning, long-horizon
autonomy, coding, tool use, multimodal reasoning, truthfulness/calibration, and safety.
It is built around a single hard rule that most leaderboards ignore —

> **The model provider runs inference. The central authority holds the answers and
> issues the score. Raw outputs flow in; answer keys and official scores never flow out.**

This repository contains a **working MVP of the trust kernel** (Phase 0) plus a
**coherent scaffold** for the rest of the platform. Read [`ANALYSIS.md`](./ANALYSIS.md)
first — it is the critical review of the design and the contract this code implements.

## Why two parts

| | **Xodexa Main App** (central) | **xodexa-runner** (self-hosted, open source) |
|---|---|---|
| Trust | Trusted scoring authority | Untrusted; runs on the provider's infra |
| Holds | Answer keys, hidden tests, signing key | Only its own keypair + the model connector |
| Can it score? | **Yes** — the only issuer of official scores | **No** — structurally incapable |
| Sees model weights? | Never | Yes (local); they never leave the provider |
| Output | Xodexa **Verified** Score, signed record | Raw model outputs + traces + signed bundle |

A provider can test locally without sending weights, prompts, or infra details to
Xodexa. But an **official** number is produced, signed, and published **only** by the
main app after verification and central re-scoring.

## What's actually built (Phase 0 — runnable today)

The trust kernel in [`packages/xodexa/`](./packages/xodexa), wired to the existing
**Xodexa-Ω gauntlet** (`../xodex_omega`) as the first benchmark pack:

- **Real Ed25519** identity, signing, and verification (`crypto.py`).
- **Hash-chained, tamper-evident event logs** — any edit breaks the chain.
- **Server-signed run manifests** with nonce + per-run task-variant generation.
- **Central re-scoring** from raw outputs using **server-held answer keys** the runner
  never sees (`authority.py`, `suites.py`).
- **Contamination defenses**: canary-echo detection, timing-anomaly detection,
  suspicious-perfect-score detection.
- **Xodexa Score** (0–1000) with weights, bounded external penalties, coverage %, grade
  bands, and a **bootstrap 95% CI** (`scoring.py`).
- **Frontier honesty metrics** (`calibration.py`): exact-match **accuracy ± Wilson CI**,
  **RMS calibration error**, and **Rank (Upper Bound)** statistical-significance ranking —
  adopted from Humanity's Last Exam. High calibration error feeds an overconfidence penalty,
  so the score itself punishes confident wrongness. See `docs/FRONTIER_BENCHMARK_DESIGN.md`.
- A **unique front page — the Frontier Observatory** (`frontend/public/index.html`):
  instead of a ranked table, models are plotted on a **capability × honesty field** with an
  unreachable **AGI horizon at 1000**; overconfident models physically sink (y = 100 −
  calibration error), a Pareto-frontier arc marks the current edge, the centerpiece **leads
  with where models break** (failure spectrum), and decimals live in a click-to-open model
  dossier (radar + accuracy ± CI + calibration). An ascent gauge shows the gap to AGI.
- A secondary **dense data view** (`frontend/public/leaderboard.html`): decimal multi-column
  table (Xodexa + 7 gauntlet sub-scores + Acc ± CI + Calib Err) with Open-LLM-style column/
  type/precision/size filters and HLE-style Rank-UB, for users who want the spreadsheet.
- **Local vs. Verified vs. Verified+Attested** score tiers, honestly labeled.
- The **xodexa-runner CLI** (`apps/runner-cli/xodexa.py`) and a FastAPI **main app**
  (`apps/server/main.py`) exposing the kernel over REST + OpenAPI.

### Run the proof

```bash
pip install cryptography
python xodexa-agi-benchmark/demo/e2e_demo.py
```

This registers a runner, issues a signed manifest, runs official + comparison scoring
against six model personas, fires every contamination check, and **proves that tampered
bundles are rejected** (edited output, edited log, replayed run). Expected tail:

```
7a edit a response  -> status=rejected  (runner_signature ok=False)
7b edit event log   -> status=rejected  (event_log_chain ok=False)
7c replay/duplicate -> status=rejected  (not_duplicate ok=False)
DEMO PASSED ✓ — trust kernel behaves correctly
```

### Use the CLI

```bash
cd xodexa-agi-benchmark
python apps/runner-cli/xodexa.py benchmark list
python apps/runner-cli/xodexa.py run --model callable:good --mode official --local
python apps/runner-cli/xodexa.py run --model callable:bluffer --mode comparison --local
python apps/runner-cli/xodexa.py verify results/<run>.bundle.json
```

Point it at a real model by swapping the connector:

```bash
# any OpenAI-compatible endpoint (vLLM / TGI / LM Studio / OpenRouter / llama.cpp)
python apps/runner-cli/xodexa.py run --model "openai:http://localhost:8000/v1#my-model" --local
# native Ollama
python apps/runner-cli/xodexa.py run --model "ollama:http://localhost:11434#llama3" --local
```

### Stand up the stack

```bash
cp xodexa-agi-benchmark/.env.example xodexa-agi-benchmark/.env   # then edit secrets
docker compose -f xodexa-agi-benchmark/docker-compose.yml up --build
# main app  -> http://localhost:8000/docs   (OpenAPI)
# dashboard -> open xodexa-agi-benchmark/frontend/public/dashboard.html
```

## What's built now — Phase 1: the platform layer

On top of the Phase-0 trust kernel, the repository now implements the **evaluation
science and data engine** in [`packages/xodexa/`](./packages/xodexa). All of it is
pure-Python + stdlib (no DB, no network) so the same code runs in CI and in an
air-gapped generator.

- **12 task families** (`families.py`): reasoning, math, science, code, agent,
  multimodal, truthfulness, safety, memory, strategy, creativity, meta_learning — rolling
  up into 12 weighted scoring dimensions.
- **A strict task schema** (`schema.py`): the `Task` dataclass with a hard, enforced
  invariant — hidden/dynamic tasks carry no `expected_answer`, and `public_view` strips
  the answer key before any task crosses the trust boundary.
- **60 procedural generators + a generation pipeline** (`generators/`, `pipeline.py`):
  each generator (`generator_id = family.subdomain`) yields *unlimited* seed-reproducible
  variants and mints a per-task canary; the pipeline runs
  `generate → difficulty_filter → contamination_filter → quality_review → calibration →
  versioning/sign`, emitting a signed, checksummed manifest. *(Multimodal items are
  text-rendered proxies in this MVP.)*
- **Contamination subsystem** (`contamination.py`): build-time similarity filtering via
  `CorpusIndex` (MinHash + shingle Jaccard + n-gram containment) and run-time canary-echo,
  timing-anomaly, and suspicious-perfect-score detection.
- **The Xodexa Score + AGI Readiness Index + Level**: the 0–1000 capability score over 12
  dimensions with bounded penalties + 95% CI (`scoring.py`), a separate AGI Readiness
  Index (10 weighted sub-scores → a 0–6 readiness level, `agi_readiness.py`), and the
  7-band grade model (`families.py`). The platform reports an *AGI-Level Candidate*, never
  actual AGI.
- **Failure analysis** (`failure_analysis.py`): a deterministic 20-type / 4-severity
  failure taxonomy with root-layer mapping.
- **The "Path to AGI" improvement roadmap engine** (`improvement.py`): turns the readiness
  profile + failure ledger into recommended next evals, fine-tuning data, RL targets, and
  scaffolding changes.
- **The plugin registry** (`registry.py`): signed, default-deny plugin manifests (no
  network, sandbox-only filesystem, no secrets, SBOM + checksum required, admin approval
  for org installs).
- **Layer-0 calibration anchors** (`anchors.py`): 25 public benchmarks (MMLU-Pro, GPQA,
  HLE, SWE-bench, GAIA, …) as metadata + adapter contracts with contamination-risk labels
  — used for calibration context only, never as the official score, and never shipped.

### The MVP seed corpus

`python scripts/build_seed.py` produces the corpus recorded in
[`datasets/SUMMARY.json`](./datasets/SUMMARY.json):

- **Xodexa Public Validation** — **1,000** tasks (answers public).
- **Xodexa Hidden Official** — **500** tasks (public views shipped; answer keys go to
  the git-ignored `server_keys/`).
- **Dynamic** — **60** generators (+ **100** sample variants).
- **Focused packs** — agent **50**, code **50**, multimodal **50**, safety **25**,
  truthfulness **25**.
- **Family minis** — **12** packs (one per family, ~40 tasks each).

### Quickstart

```bash
pip install -r requirements.txt   # cryptography + FastAPI stack
python scripts/build_seed.py      # build the seed corpus (datasets/ + server_keys/)
python demo/platform_demo.py      # evaluate → score → AGI readiness → improvement roadmap
python demo/e2e_demo.py           # Phase-0 trust kernel + tamper-proof verification
```

### Documentation

- [`docs/DATASET_GENERATION.md`](./docs/DATASET_GENERATION.md) — philosophy, the 6-layer
  architecture, the schema, the generators, the pipeline, and how to add a generator.
- [`docs/AGI_READINESS.md`](./docs/AGI_READINESS.md) — the Xodexa Score, the AGI Readiness
  Index + Levels, the failure taxonomy, and the improvement roadmap.
- [`docs/SECURITY_MODEL.md`](./docs/SECURITY_MODEL.md) — the trust boundary, signing,
  hash-chained logs, the two score types, and what crypto does/doesn't prove.
- [`docs/PLUGIN_GUIDE.md`](./docs/PLUGIN_GUIDE.md) — building, signing, and installing a
  plugin under the enforced security policy.
- [`docs/RUNNER.md`](./docs/RUNNER.md) — the self-hosted runner: connectors, the official
  scoring flow, and the CLI commands.
- [`docs/FRONTIER_BENCHMARK_DESIGN.md`](./docs/FRONTIER_BENCHMARK_DESIGN.md) — the Open-LLM
  + HLE synthesis behind the leaderboard.

## Architecture

```
   MODEL PROVIDER INFRA                         APEXAGI CENTRAL (trusted)
 ┌──────────────────────────┐   register     ┌──────────────────────────────┐
 │ xodexa-runner           │ ─────────────▶ │ Scoring Authority            │
 │  • runner keypair        │   manifest     │  • server keypair            │
 │  • model connector       │ ◀───────────── │  • answer keys (never leave) │
 │  • inference only        │                │  • per-run task variants     │
 │  • hash-chained log      │   submit raw   │  • verify sig+chain+nonce    │
 │  • signs result bundle   │ ─────────────▶ │  • RE-SCORE centrally        │
 │  → LOCAL score (advisory)│                │  • canary/timing/contam      │
 └──────────────────────────┘                │  • Xodexa Score + status       │
        answers never arrive ◀───────────────│  • publish signed record     │
                                              └──────────────────────────────┘
```

Layout:

```
xodexa-agi-benchmark/
├─ ANALYSIS.md            critical review + improved architecture (read first)
├─ packages/xodexa/     trust kernel: crypto, scoring, suites, authority, runner
├─ apps/server/           FastAPI main app (scoring authority) + Dockerfile
├─ apps/runner-cli/       xodexa CLI (the open-source runner)
├─ demo/e2e_demo.py       end-to-end proof incl. tamper tests
├─ db/schema.sql          full PostgreSQL schema (Phase 1)
├─ api/openapi.yaml       REST contract
├─ frontend/              dark research-lab UI (static demo now, Next.js app Phase 6)
├─ seed/                  placeholder models + benchmark packs
├─ docker-compose.yml     Postgres + Redis + MinIO + server
└─ requirements.txt
```

## Scoring: Local vs. Verified

| Tier | Who issues it | Trust level |
|---|---|---|
| **Local score** | the runner (comparison mode only) | advisory; graders were shipped; never official |
| **Verified, non-attested** | the main app | re-scored centrally; trusts the provider didn't look up answers |
| **Verified + Attested** | the main app | adds a confidential-computing attestation (SEV-SNP / TDX / Nitro / CVM) of the execution environment |

The Xodexa Score is **0–1000** (Weak < 200 ≤ Basic < 400 ≤ Strong < 600 ≤ Frontier < 750
≤ Proto-AGI < 900 ≤ AGI-Level Candidate), computed over **evaluated categories only**
with coverage reported, penalties bounded, and a 95% CI attached. A bare number is never
shown.

## Threat model (read this honestly)

Cryptography here proves **identity** (who produced a bundle), **integrity** (it wasn't
altered after signing), **ordering** (the log wasn't silently edited), and **freshness**
(no replay). It does **not** prove which model actually ran, nor that the provider didn't
look up answers during inference. The defenses that actually matter, in order:

1. **The runner never gets answer keys or hidden tests.** Central re-scoring from raw
   outputs is the default and is non-optional for official scores.
2. **Contamination resistance is the real moat** — per-run generated task variants,
   private hidden sets with rotation, canaries, and central hidden-test execution. Crypto
   is secondary to this.
3. **Attestation** is the only thing that upgrades "we trust the provider's honesty" to
   "we trust the silicon," and most labs won't run it — so *Verified, non-attested* is
   the honest common tier and the UI never lets it masquerade as more.

**No self-hosted benchmark can be made perfectly cheat-proof** unless execution, hidden
tests, and scoring are centrally controlled or remotely attested. Xodexa reduces — not
eliminates — cheating risk, and says so.

## Roadmap (see ANALYSIS.md §5 for the full build order)

- **Phase 0 ✅** Trust kernel + Xodexa-Ω pack + CLI + tamper-proof e2e demo *(this MVP)*.
- **Phase 1** FastAPI ↔ Postgres persistence, full REST, leaderboard read API.
- **Phase 2** Adapters: lm-eval-harness & Inspect AI first, then HELM / OpenCompass /
  OpenAI-Evals import-export (all feeding raw outputs into central scoring).
- **Phase 3** Data engine: push Layer-2 procedural generation; wire Layer-1 public packs
  (MMLU-Pro, GPQA-Diamond, SWE-bench-Verified, LiveCodeBench, BigCodeBench, GAIA,
  tau-bench) as comparison-only; Layer-3 private rotation + canary leak detection.
- **Phase 4** Agentic gauntlets over hardened, deterministic, replayable tool sandboxes.
- **Phase 5** Cosign/SLSA/in-toto provenance; optional attestation (Nitro first); signed
  plugin marketplace with static analysis; multi-tenant private-eval isolation.
- **Phase 6** Full Next.js UI depth (radar/heatmap/failure-matrix/compare/reports).

## Benchmark adapter guide (the integration pattern)

Every adapter follows `packages/xodexa/suites.py`: expose `expand_for_run(pack, seed)`
returning `(public_tasks, answer_keys)` where **prompts ship to the runner and graders
stay central**, and `grade_response(key, output)` for central re-scoring. Map your tasks'
categories onto the nine Xodexa categories. That's the whole contract.

## License

Licensed under **Apache-2.0** — anyone may use, modify, and commercialize the software.
Copyright and the *Xodexa* trademarks remain owned by Maninder Singh; the license covers
the code, not the brand, and official scoring is reserved to the central authority. See
the repo-root `LICENSE`, `NOTICE`, and `CLA.md`.
