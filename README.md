<div align="center">

# 🛰️ Xodexa AGI Benchmark

### Built to break the best.

**The world's most unforgiving open benchmark for frontier AI — we don't rank models, we measure how far they fall short of AGI.**

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](#-license)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg?logo=python&logoColor=white)](#)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688.svg?logo=fastapi&logoColor=white)](#)
[![Crypto](https://img.shields.io/badge/verification-Ed25519%20signed-7c5cff.svg)](#-the-trust-model-the-hard-part)
[![Status](https://img.shields.io/badge/status-Phase%200%20MVP%20(runnable)-27d796.svg)](#-roadmap)
[![Contamination](https://img.shields.io/badge/anti--memorization-per--run%20generated-ff5d6c.svg)](#-why-its-hard-and-honest)

*Open-source-first · self-hostable · cryptographically verified central scoring · calibration-aware*

</div>

---

## 🌌 What is this?

Most AI leaderboards reward models for sounding confident and matching the shape of
familiar problems — so they **saturate** and **leak** the moment a benchmark gets
popular. Xodexa AGI Benchmark inverts the incentives. It is engineered to **fail**
capable models, **legitimately**, and to quantify exactly *how* and *how far* they fall
short — across reasoning, long-horizon autonomy, coding, tool use, multimodal reasoning,
truthfulness, and safety.

Two ideas make it different from everything else:

1. **Honesty is a coordinate, not a footnote.** A brilliant-but-overconfident model
   physically *sinks* on our front page, because we plot capability against calibration.
   This is the failure mode [Humanity's Last Exam](https://labs.scale.com/leaderboard/humanitys_last_exam)
   found in *every* frontier model — and we score it.
2. **A number on this board can't be faked.** The model provider runs inference; the
   central authority holds the answers and issues the score. **Raw outputs flow in;
   answer keys and official scores never flow out** — enforced with Ed25519 signing,
   hash-chained logs, per-run generated task variants, canaries, and central re-scoring.

> **The one-line thesis:** a benchmark becomes the industry standard when it is hard
> enough not to saturate, broad enough to mean *capability*, honest enough to expose
> confident wrongness, and trustworthy enough that the score can't be gamed. Xodexa is
> the combination.

---

## 🧭 Repository layout

This repo is the umbrella for two components:

```
XodexaAGIBenchmark/
├── xodexa-agi-benchmark/      # 🏛️  The platform — trust kernel, scoring authority, runner, UI
│   ├── packages/xodexa/       #     Ed25519 crypto · scoring · calibration · suites · authority · runner
│   ├── apps/server/           #     FastAPI scoring authority (central, trusted)
│   ├── apps/runner-cli/       #     `xodexa` CLI — the open-source self-hosted runner
│   ├── demo/e2e_demo.py       #     End-to-end proof incl. tamper tests (fails closed)
│   ├── frontend/public/       #     The "Frontier Observatory" front page + data views
│   ├── db/schema.sql · api/openapi.yaml · docker-compose.yml
│   ├── ANALYSIS.md · docs/FRONTIER_BENCHMARK_DESIGN.md · DEPLOYMENT.md
│   └── README.md              #     Full platform docs
│
└── xodex_omega/               # ⚔️  Xodexa-Ω — the seed gauntlet (the question engine)
    ├── harness.py             #     Deterministic graders + run-time task generation
    ├── dataset.jsonl          #     25 brutal, anti-memorization items (92 pts)
    └── Xodexa-Omega_Specification.docx
```

- **Xodexa AGI Benchmark** (`xodexa-agi-benchmark/`) — the production platform: the
  cryptographic trust kernel, the central scoring authority, the self-hosted runner, the
  0–1000 **Xodexa Score**, and the leaderboard UI.
- **Xodexa-Ω** (`xodex_omega/`) — the first benchmark pack: a self-contained, deterministic
  gauntlet of adversarial reasoning, long-context, hallucination-resistance, and novel
  un-memorizable problems, wired into the platform as `xodexa-omega`.

---

## ⚡ Quickstart

```bash
# 0) one dependency for the trust kernel
pip install cryptography

# 1) Prove the whole trust model end-to-end (no API key, no server needed).
#    Registers a runner, issues a signed manifest, scores 6 model personas,
#    fires every contamination check, and PROVES tampered bundles are rejected.
python xodexa-agi-benchmark/demo/e2e_demo.py

# 2) Run the Xodexa-Ω gauntlet's self-test (oracle 100% / adversary < 0 / blank 0).
python xodex_omega/harness.py selftest

# 3) Drive the runner CLI locally.
cd xodexa-agi-benchmark
python apps/runner-cli/xodexa.py benchmark list
python apps/runner-cli/xodexa.py run --model callable:good --mode official --local

# 4) Open the front page (the Frontier Observatory).
open frontend/public/index.html        # macOS  (xdg-open on Linux)
```

Point the runner at a real model by swapping the connector:

```bash
# any OpenAI-compatible endpoint (vLLM / TGI / LM Studio / OpenRouter / llama.cpp)
python apps/runner-cli/xodexa.py run --model "openai:http://localhost:8000/v1#my-model" --local
# native Ollama
python apps/runner-cli/xodexa.py run --model "ollama:http://localhost:11434#llama3" --local
```

---

## 🔭 The Frontier Observatory (front page)

Not a ranked table — a **map**. Each model is plotted by two coordinates:

- **x = capability** (the Xodexa Score, 0 → an **AGI horizon at 1000 that nothing reaches**)
- **y = honesty** (100 − RMS calibration error, so confidently-wrong models *sink*)

A glowing Pareto-frontier arc marks the current edge of the possible; the centerpiece
**leads with where models break** (per-gauntlet failure spectrum); decimals live in a
click-to-open dossier (radar + accuracy ± CI + calibration). See
`xodexa-agi-benchmark/frontend/public/index.html`.

---

## 🔐 The trust model (the hard part)

```
   MODEL PROVIDER INFRA                          XODEXA CENTRAL (trusted)
 ┌──────────────────────────┐   register      ┌──────────────────────────────┐
 │ xodexa-runner (OSS)      │ ──────────────▶ │ Scoring Authority            │
 │  • runner keypair        │   signed mfst   │  • server keypair            │
 │  • model connector       │ ◀────────────── │  • answer keys (never leave) │
 │  • inference ONLY        │                 │  • per-run task variants     │
 │  • hash-chained log      │   raw outputs   │  • verify sig+chain+nonce    │
 │  • signs result bundle   │ ──────────────▶ │  • RE-SCORE centrally        │
 │  → LOCAL score (advisory)│                 │  • canary/timing/contam      │
 └──────────────────────────┘                 │  • Xodexa Score + status     │
        answers never arrive ◀────────────────│  • publish signed record     │
                                               └──────────────────────────────┘
```

| Score tier | Issued by | Trust level |
|---|---|---|
| **Local** | the runner (comparison mode only) | advisory; never official |
| **Verified, non-attested** | the central authority | re-scored centrally; trusts the provider didn't look up answers |
| **Verified + Attested** | the central authority | adds confidential-computing attestation (SEV-SNP / TDX / Nitro / CVM) |

**Honest threat model:** cryptography proves *identity*, *integrity*, *ordering*, and
*freshness* — it does **not** prove which model ran or that no one looked up answers.
The real moat is **contamination resistance** (per-run generated variants, private hidden
sets, canaries, central hidden-test execution). No self-hosted benchmark is perfectly
cheat-proof without attestation — and we say so. Full write-up in
[`xodexa-agi-benchmark/ANALYSIS.md`](xodexa-agi-benchmark/ANALYSIS.md).

---

## 🧮 Scoring

The **Xodexa Score** is a 0–1000 composite, re-scored centrally from raw outputs, with a
**bootstrap 95% CI**, a **coverage %** (evaluated categories only — no cherry-picking),
and bounded penalties for hallucination, overconfidence, canary leakage, and contamination.

| Score | Grade |
|--:|---|
| 0–199 | Weak |
| 200–399 | Basic |
| 400–599 | Strong |
| 600–749 | Frontier |
| 750–899 | Proto-AGI |
| 900–1000 | AGI-Level Candidate *(audit for contamination)* |

Frontier honesty metrics — **accuracy ± Wilson CI**, **RMS calibration error**, and
**Rank (Upper Bound)** statistical-significance ranking — are adopted from HLE and
implemented in `packages/xodexa/calibration.py`. Design rationale:
[`docs/FRONTIER_BENCHMARK_DESIGN.md`](xodexa-agi-benchmark/docs/FRONTIER_BENCHMARK_DESIGN.md).

---

## 🧨 Why it's hard (and honest)

- **Negative marking** — a confident hallucination scores *below zero*. "I can't verify
  that" beats inventing detail.
- **Trap calibration** — items are near-clones of canonical puzzles (Monty Hall,
  bat-and-ball, pound-of-feathers) with one altered assumption that flips the answer.
- **Anti-memorization by construction** — long-context tasks are generated per run from a
  seed; the dataset cannot be leaked the way a fixed question bank can.
- **Deterministic grading** — no LLM judge; every score is reproducible and auditable.

---

## 🚀 Deployment

Use **Vercel for the frontend** and **Railway for the stateful scoring authority +
Postgres/Redis** — Vercel's serverless model can't host the always-on, secret-holding
authority. Full guide, env vars, and step-by-step:
[`xodexa-agi-benchmark/DEPLOYMENT.md`](xodexa-agi-benchmark/DEPLOYMENT.md).

---

## 🗺️ Roadmap

- **Phase 0 ✅** Trust kernel + Xodexa-Ω pack + CLI + tamper-proof e2e demo *(this MVP)*
- **Phase 1** FastAPI ↔ Postgres persistence, full REST, leaderboard API
- **Phase 2** Adapters: lm-eval-harness & Inspect AI first, then HELM / OpenCompass / OpenAI-Evals
- **Phase 3** Data engine: procedural generation + public packs (MMLU-Pro, GPQA-Diamond, SWE-bench-Verified, LiveCodeBench, BigCodeBench, GAIA, tau-bench) as comparison-only + Layer-3 private rotation
- **Phase 4** Agentic gauntlets over hardened, deterministic, replayable tool sandboxes
- **Phase 5** Cosign/SLSA/in-toto provenance, optional attestation, signed plugin marketplace
- **Phase 6** Full Next.js UI depth (radar / heatmap / failure-matrix / compare / reports)

---

## 🤝 Contributing

Adapters follow one contract (`packages/xodexa/suites.py`): expose
`expand_for_run(pack, seed) -> (public_tasks, answer_keys)` where **prompts ship to the
runner and graders stay central**, plus `grade_response(key, output)` for central
re-scoring. Map your tasks' categories onto the nine Xodexa categories. Re-run the
gauntlet self-test before trusting a new item.

## 📄 License

Apache-2.0 (recommended) — permissive enough for labs to self-host and extend. See
`LICENSE`.

<div align="center">

**Xodexa AGI Benchmark** — *we don't rank AI, we map how far it falls short.*

</div>
