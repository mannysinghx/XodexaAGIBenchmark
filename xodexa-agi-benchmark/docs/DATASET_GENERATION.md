# Dataset Generation

How the Xodexa AGI Benchmark builds tasks that **cannot be faked by memorization**.
This document describes the dataset philosophy, the layered architecture, the strict
task schema, the procedural generators, and the generation pipeline that turns raw
generator output into a signed, contamination-filtered release.

Everything here is implemented in `packages/xodexa/` and is pure-Python + stdlib (no
network, no DB), so the same code runs in CI and in an air-gapped generator.

---

## 1. Philosophy — "100x better, not 100x bigger"

A bigger dataset is not a harder one. The week a benchmark's questions leak into a
training set, the benchmark is dead. So Xodexa optimizes for **un-leakability and
discrimination at the frontier**, not raw item count (see `ANALYSIS.md` §1.2 — *"the
hardest benchmark on Earth is worthless the week its questions leak"*).

Three commitments follow from this:

- **Procedural generation is first-class, not an afterthought.** A single deterministic
  generator yields *unlimited* seed-reproducible variants; change the seed and you get a
  fresh, memorization-resistant item. This is the only truly un-leakable layer.
- **Answers never leave the trust boundary.** Hidden and dynamic tasks carry no
  `expected_answer`; the schema enforces this (`schema.new_task` blanks it), and answer
  keys for hidden sets are written to a git-ignored `server_keys/` directory.
- **Every release is filtered, calibrated, and signed.** A task earns its place by
  passing similarity filtering and grader-satisfiability review, and a release ships with
  a signed, checksummed manifest that records why each task was kept or dropped.

---

## 2. The 6-layer dataset architecture

| Layer | Name | What it is | Where in code |
|---|---|---|---|
| **0** | Public calibration anchors | Public, industry-standard benchmarks (MMLU-Pro, GPQA, HLE, SWE-bench, GAIA, …) used only to *calibrate and contextualize*, never as the official score. Metadata + adapter contract; content is **not shipped**. | `anchors.py` |
| **1** | Public validation set | Generated tasks shipped **with** answer keys so anyone can self-test. MVP: 1,000 tasks. | `pipeline.py`, `scripts/build_seed.py` |
| **2** | Private hidden official set | Generated tasks shipped as **public views only** (answers withheld). The official hidden score is computed from these. MVP: 500 tasks; keys → `server_keys/`. | `scripts/build_seed.py` |
| **3** | Dynamic runtime-generated set | Tasks minted **per run** from a server nonce, so the variant a runner sees is unique and its key is retained centrally. Backed by the generator registry. | `generators/`, `authority.issue_manifest` |
| **5** | Human baselines | Per-family human/expert scores (`HumanBaseline`) that turn provisional difficulty into empirical difficulty and enable human-parity scoring. Illustrative values in the MVP. | `schema.HumanBaseline`, `report._human_comparison` |
| **6** | AGI strategy | The readiness/diagnosis layer that consumes the above: AGI Readiness Index, failure taxonomy, improvement roadmap. | `agi_readiness.py`, `failure_analysis.py`, `improvement.py` |

> Layer 4 (human-review workflow) and full Layer-5 baseline collection are roadmap items;
> the MVP wires Layers 0–3, ships illustrative Layer-5 baselines, and implements Layer 6.

---

## 3. The 12 task families

The canonical taxonomy lives in `families.FAMILIES`. Each `Family` has a `key`, `title`,
`blurb`, and a tuple of `subdomains`.

| Family key | Title |
|---|---|
| `reasoning` | Reasoning Gauntlet |
| `math` | Mathematics Gauntlet |
| `science` | Science Gauntlet |
| `code` | Code & Software Engineering Gauntlet |
| `agent` | Agentic Autonomy Gauntlet |
| `multimodal` | Multimodal Gauntlet |
| `truthfulness` | Truthfulness & Calibration Gauntlet |
| `safety` | Safety & Robustness Gauntlet |
| `memory` | Memory & Context Gauntlet |
| `strategy` | Strategy & Decision-Making Gauntlet |
| `creativity` | Creativity & Synthesis Gauntlet |
| `meta_learning` | Meta-Learning & Adaptation Gauntlet |

Families roll up into the 12 official scoring **dimensions** via
`families.FAMILY_TO_DIMENSION` (e.g. `math → mathematics`, `agent → agentic_autonomy`).
`creativity` and `meta_learning` have no dedicated headline weight; they fold into
`reasoning` for the Xodexa Score and surface separately in the AGI Readiness
Generality/Transfer sub-scores. See [AGI_READINESS.md](./AGI_READINESS.md).

---

## 4. The strict task schema

Every task is a `schema.Task` dataclass (stdlib only — no pydantic — so the engine stays
importable in an air-gapped runner). Key fields:

| Field | Type | Notes |
|---|---|---|
| `task_id` | `str` | Stable, derived from `generator_id : seed : idx`. |
| `task_family` | `str` | One of the 12 family keys. |
| `subdomain` | `str` | A subdomain from the family. |
| `prompt` | `str` | The shippable prompt (includes a canary control-token suffix). |
| `expected_answer_type` | `str` | `exact` / `numeric` / `code_patch` / `rubric` / `final_state` / `proof` / `structured_json`. |
| `difficulty` | `float` | 0–10; provisional until baselines exist. |
| `difficulty_band` | `str` | Derived via `families.difficulty_band` (easy…superhuman). |
| `visibility` | `str` | `public` / `validation` / `private_hidden` / `dynamic`. |
| `modality` | `list[str]` | Subset of `text/image/audio/video/code/tool_use`. |
| `requires_tools`, `tools_allowed` | `bool`, `list` | Agentic tasks. |
| `input_assets` | `list[dict]` | E.g. text-rendered figures for multimodal. |
| `expected_answer` | `Any` | **Public/validation only.** Blanked for hidden/dynamic. |
| `server_grader` | `dict \| None` | Deterministic grader spec; **never** in a public view. |
| `hidden_tests` | `str` | `"server_side_only"` by default. |
| `scoring_rubric` | `dict` | Weights summing to 1.0 (`DEFAULT_RUBRIC`). |
| `human_baseline` | `HumanBaseline` | Layer-5 baselines. |
| `contamination_controls` | `ContaminationControls` | `canary`, `generated_at`, `source_hash`, `public_similarity_score`, `release_status`. |
| `provenance` | `Provenance` | `created_by`, `review_status`, `reviewer_count`, `license`. |
| `safety_notes` | `SafetyNotes` | `risk_domain`, `harmful_content_removed`. |
| `points`, `negative` | `float` | Positive credit and the negative-marking penalty for confident-wrong. |

Two security-critical invariants the schema **enforces**:

1. `expected_answer` is populated only for `public`/`validation` tasks. For
   `private_hidden` and `dynamic` tasks it is forced to `None` in `new_task`, and
   `validate_task` rejects any hidden/dynamic task that still carries one.
2. The answer key (`expected_answer`, `server_grader`, `hidden_tests`) is stripped before
   a task crosses the trust boundary via `schema.public_view`. The canary stays (we *want*
   to detect echoes); the grader and answer go.

```python
from xodexa.schema import new_task, validate_task, public_view, answer_key

t = new_task(
    task_id="demo_1", task_family="reasoning", subdomain="hidden_rule_induction",
    prompt="A function f follows a hidden rule. f(3)=10 ... What is f(20)?",
    expected_answer_type="numeric",
    server_grader={"type": "numeric", "target": 67.0, "tolerance": 0.001},
    expected_answer=67, difficulty=4.0, visibility="public",
)
assert validate_task(t) == []          # [] means valid
shippable = public_view(t)             # answer key stripped — safe to send to a runner
key = answer_key(t)                    # server-side key for central re-scoring
```

`answer_key()` also resolves the task family to its scoring dimension via
`FAMILY_TO_DIMENSION` and carries `points`, `negative`, and the `canary`.

---

## 5. How generators work

### Registry and IDs

Generators live in `packages/xodexa/generators/` (one module per family). Each is a small
deterministic function `gen(rng, idx, visibility) -> Task` registered under a stable
`generator_id` of the form **`family.subdomain`**:

```python
from xodexa.generators import register, mk_canary, mk_id, canary_suffix
from xodexa.schema import new_task

@register("reasoning.hidden_rule_induction", "reasoning")
def hidden_rule_induction(rng, idx, vis):
    """Induce a hidden numeric mapping from examples, then apply it."""
    a, b = rng.randint(2, 5), rng.randint(1, 9)
    ...
    c = mk_canary(rng)
    return new_task(mk_id(rng, "reasoning.hidden_rule_induction"),
                    "reasoning", "hidden_rule_induction", prompt + canary_suffix(c),
                    "numeric",
                    server_grader={"type": "numeric", "target": float(ans), "tolerance": 0.001},
                    expected_answer=ans, difficulty=4.0, visibility=vis,
                    points=3, negative=2, canary=c)
```

The `@register(generator_id, family, blurb="")` decorator records a `GeneratorSpec` into
the module-level `REGISTRY` dict and rejects duplicate IDs. Family modules are imported at
package load (`_load_family_modules`) so their decorators run.

### Seed reproducibility

Determinism comes entirely from the seed. `generate_from`, `generate`, and the per-task
RNGs are all seeded with `sha256_int("generator_id:seed[:i]")`, so:

- the **same** seed reproduces the **same** corpus byte-for-byte, and
- a **new** seed yields a fresh, memorization-resistant variant.

```python
from xodexa import generators as G

# all generators in a family, n tasks, round-robin
tasks = G.generate(family="reasoning", n=100, seed=1001, visibility="public")

# a single generator
tasks = G.generate_from("safety.prompt_injection", n=20, seed=42, visibility="dynamic")

# the catalogue
specs = G.list_generators()            # sorted GeneratorSpec list
```

### Canary minting

Every generated task mints a per-task canary token (`mk_canary` / `canary` helpers) and
appends it to the prompt as a control-token instruction the model is told to ignore. If
the canary later appears in the model's output, that is a strong context-dump /
training-leak signal — consumed at run time by `contamination.canary_echo_count` and by
the central authority. See [SECURITY_MODEL.md](./SECURITY_MODEL.md).

### Unlimited variants; multimodal proxies (honest statement)

- The MVP ships **60 procedural generators** (confirmed by `datasets/SUMMARY.json`
  `dynamic.generator_count = 60`), spread across all 12 families. Each yields *unlimited*
  seed-reproducible variants — the catalogue is the thing the platform exposes as "N
  dynamic task generators".
- **Multimodal items are text-rendered proxies in the MVP.** `generators/multimodal.py`
  renders a "figure" as a deterministic text table / ASCII chart referenced via
  `input_assets`, and tags `modality=["image","text"]` to mark intent. This keeps the
  grader exact while matching the multimodal task shape; real deployments attach actual
  image/figure assets. This limitation is also recorded in every release manifest's
  `known_limitations`.

---

## 6. The generation pipeline

`pipeline.DatasetPipeline` runs a composable, auditable stage chain
(`pipeline.py`, mirroring the spec's stages 1–6):

```
generate → difficulty_filter → contamination_filter → quality_review
         → calibration → versioning(+sign)
```

| Stage | What it does |
|---|---|
| **generate** | Tasks come in (from the generators). The driver records the input count. |
| **difficulty_filter** | If `probe_models` are supplied, keep only tasks whose frontier pass-rate sits in `[keep_min_passrate, keep_max_passrate]` (default `(0.0, 0.95]`) — too-easy and impossible items are dropped, and empirical difficulty/discrimination is annotated. Without probes it is a pass-through. |
| **contamination_filter** | Scores each prompt's similarity against the `CorpusIndex` and drops anything `>= contamination_threshold` (default 0.6). Records `public_similarity_score` on every kept task. |
| **quality_review** | Schema validation; grader-satisfiability check (`grade.synth_good` must earn full credit if `require_grader_satisfiable`); flags high-stakes families (`science/math/code/safety`) for expert review. |
| **calibration** | Assigns discrimination, expected human solve-time, and inter-rater-agreement heuristics. |
| **versioning + sign** | Builds `public_tasks` (public views), `answer_keys` (server-side), a deterministic checksum over the shippable views, and a **signed** manifest with difficulty distribution, contamination summary, family/visibility/license rollups, the pipeline trace, and `known_limitations`. |

```python
from xodexa import generators as G
from xodexa.pipeline import DatasetPipeline
from xodexa.contamination import CorpusIndex
from xodexa.crypto import KeyPair

tasks = G.generate(family="safety", n=25, seed=7007, visibility="validation")
rel = DatasetPipeline(corpus=CorpusIndex(), signer=KeyPair.generate()).run(
    tasks, name="Xodexa Safety Mini", version="1.0.0",
    changelog="MVP seed build")

rel.public_tasks   # answer-key-stripped views — safe to ship
rel.answer_keys    # {task_id: answer_key} — NEVER shipped
rel.manifest       # signed, checksummed manifest
rel.signature      # Ed25519 signature over the manifest
rel.stats          # per-stage in/out counts
rel.rejected       # every dropped task + reason
```

`PipelineConfig` exposes the knobs: `contamination_threshold`, `keep_min_passrate`,
`keep_max_passrate`, `require_grader_satisfiable`, `expert_review_families`.

---

## 7. Adding a new generator

1. Pick a `family` (one of the 12 keys) and a `subdomain` (ideally from that family's
   `subdomains` tuple), giving a `generator_id` of `family.subdomain`.
2. In the family's module under `generators/` (or a new module imported in
   `_load_family_modules`), write `gen(rng, idx, vis) -> Task` and decorate it:

```python
@register("reasoning.my_new_probe", "reasoning")
def my_new_probe(rng, idx, vis):
    """One-line blurb (used as the catalogue description)."""
    n = rng.randint(2, 9)                     # all randomness via rng -> reproducible
    answer = n * n
    c = mk_canary(rng)
    prompt = f"Square the number {n}. Give only the number." + canary_suffix(c)
    return new_task(
        mk_id(rng, "reasoning.my_new_probe"), "reasoning", "my_new_probe",
        prompt, "numeric",
        server_grader={"type": "numeric", "target": float(answer), "tolerance": 0.001},
        expected_answer=answer, difficulty=2.0, visibility=vis,
        points=1, negative=0, canary=c)
```

Rules that keep it correct and safe:

- **Use only `rng`** for randomness so the generator is seed-reproducible.
- **Always mint a canary** and pass it to `new_task(canary=...)`.
- **Provide a `server_grader`** whose type is supported by `grade.grade` (`exact`, `mcq`,
  `numeric`, `numeric_set`, `contains_all`, `contains_any`, `regex`,
  `flag_false_premise`, `abstain`, `rubric_keywords`, `structured_json`).
- **Make the grader satisfiable**: `grade.synth_good(grader)` must earn full credit and
  `grade.synth_bad(grader)` should be net-penalized (the quality-review stage enforces the
  first; this is the Ω self-test contract generalized to all packs).
- **Safety packs stay benign** — abstracted, non-operational scenarios only (see
  `generators/safety.py`).

The new generator is automatically picked up by `list_generators()`, `generate()`, the
dynamic catalogue, and `build_seed.py`.

---

## 8. Running `scripts/build_seed.py`

```bash
python scripts/build_seed.py            # full MVP seed corpus
python scripts/build_seed.py --quick    # ~5% scale, CI smoke test
```

It generates and signs every release, writing under `datasets/` (and hidden answer keys
under git-ignored `server_keys/`):

- **Layer 1 — Xodexa Public Validation:** 1,000 tasks, answers public.
- **Layer 2 — Xodexa Hidden Official:** 500 tasks, public views shipped, keys → `server_keys/`.
- **Layer 3 — Dynamic:** the 60-generator catalogue + 100 sample variants.
- **Focused packs:** agent (50), code (50), multimodal (50), safety (25), truthfulness (25).
- **Family minis:** one ~40-task pack per family (12 packs).

Per release it writes `tasks_public_view.jsonl`, `manifest.json`, `manifest.sig`,
`rejected.json`, and an `*.answer_keys.json` (to the release dir for public packs, to
`server_keys/` for the hidden set), then a top-level `datasets/SUMMARY.json`. Family
allocation for the large sets is weighted by scoring weight with a floor of 25 per family
(`_family_allocation`).

The exact counts produced by the last full build are recorded in `datasets/SUMMARY.json`
and summarized in the project [README](../README.md).
