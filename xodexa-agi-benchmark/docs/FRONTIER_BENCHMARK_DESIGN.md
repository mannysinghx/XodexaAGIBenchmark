# Frontier Leaderboard Design — analysis & the Xodexa synthesis

This note analyzes the two reference leaderboards the user pointed at — the **Hugging
Face Open LLM Leaderboard** and **Scale AI's Humanity's Last Exam (HLE)** — and specifies
how Xodexa AGI Benchmark fuses and advances both into a single industry-grade board.

## 1. What each reference does well

### Open LLM Leaderboard (Hugging Face)
- **Decimal multi-benchmark columns.** One row per model; columns are `Average` plus
  per-benchmark scores (ARC, HellaSwag, MMLU, TruthfulQA, Winogrande, GSM8K), all shown
  to two decimals.
- **Heavy faceting.** Column show/hide toggles; filters for model *type* (pretrained /
  continuously-pretrained / fine-tuned / chat / merge), *precision* (fp16/bf16/8bit/4bit/
  GPTQ), *size* buckets (~1.5B … 70B+), and "hide" switches (private/deleted, merges,
  flagged, MoE).
- **At-a-glance typing.** Icons mark each model's training type.

Weakness: the underlying benchmarks (MMLU, ARC, …) are **saturated and contaminated** —
near-ceiling for frontier models and leak-prone — so the board no longer discriminates at
the top, and a single `Average` hides *how* a model is strong.

### Humanity's Last Exam (Scale AI / CAIS)
- **Frontier-hard, un-saturating.** 2,500 expert-authored, subject-diverse, **multimodal**
  (14% need a figure), **closed-ended** questions; ~24% multiple choice. Top models score
  low single digits to ~46%, so the board has headroom for years.
- **Honesty is a first-class metric.** Reports **accuracy** *and* **RMS calibration
  error** (CE). HLE's central empirical finding: frontier models pair low accuracy with
  **>80% CE** — i.e. they are confidently wrong (confabulation).
- **Statistically rigorous ranking.** Models are ranked by **Rank (Upper Bound)**:
  `rank = 1 + #{models whose lower 95% CI bound exceeds this model's upper bound}`.
  Statistically tied models share a rank — no false precision from raw-score sorting.
- **Contamination defense by construction.** A **held-out private set** measures
  overfitting; "searchable" questions were audited out; difficulty bar requires questions
  to stump several frontier models before human review.

Weakness: HLE is one exam (academic, closed-ended). It deliberately says high HLE accuracy
"would not alone suggest … AGI" — it doesn't cover coding, long-horizon autonomy, tool use,
or agentic safety, and it has no execution-integrity / verification layer (it evaluates
provider-reported or hosted outputs).

## 2. The Xodexa synthesis — taking the best of both, then going further

| Dimension | Open LLM | HLE | **Xodexa AGI Benchmark** |
|---|---|---|---|
| Score granularity | decimals, many columns | accuracy + CE | **decimals everywhere**: Xodexa 0–1000 + 7 gauntlet sub-scores + accuracy + CE |
| Difficulty | saturated | frontier, un-saturating | frontier (Xodexa-Ω + Frontier-Exam pack) **with negative marking** |
| Honesty metric | TruthfulQA only | **RMS calibration error** | calibration error **folded into the score** as an overconfidence penalty + shown as a column |
| Ranking | raw average sort | **Rank (Upper Bound)** | **Rank (UB)** on Xodexa Score *and* on exam accuracy; bootstrap 95% CI on Xodexa |
| Faceting | rich | minimal | **rich** (columns, type, precision, size) **+ verification facets** |
| Contamination | weak | held-out private set | held-out private set **+ per-run generated variants + canaries + central re-score** |
| Execution integrity | none | none | **Ed25519-signed, centrally re-scored, tamper-evident** (Local / Verified / Verified+Attested) |
| Breadth | reasoning/QA | one academic exam | **9 capability categories** with coverage % shown |

The result is the board described in `frontend/public/leaderboard.html`:
- **Decimal columns** for `Xodexa ⬆`, `Acc ± CI`, `Calib Err`, and each gauntlet
  (Reasoning, Long-Horizon, Truthful, Code, Agent, Multimodal, Safety), plus Cost & Latency.
- **Rank (UB)** computed live from accuracy ± CI (HLE's exact rule).
- **Honesty map** — an accuracy-vs-calibration scatter that makes HLE's "frontier ≠
  calibrated" finding visible at a glance (bubble size = Xodexa Score).
- **Verification badges** (Attested ▸ Verified ▸ Local) and **contamination flags** that
  no other public board has, because no other board re-scores from raw outputs centrally.
- Open-LLM-style **column toggles** and **type / precision / size filters**.

## 3. What was added to the engine to support this

- `xodexa/calibration.py` — real implementations of:
  - `rms_calibration_error()` (Hendrycks-style binned RMS-CE, 0–100),
  - `wilson_ci()` (95% CI on a proportion, accurate near the 0% accuracies HLE lives at),
  - `rank_upper_bound()` (HLE's significance ranking),
  - `accuracy()`.
- `authority.py` now computes, on every official run, **exact-match accuracy ± CI** and
  **calibration error** from per-item correctness and model-stated confidence, and applies
  an **overconfidence penalty** when CE is high (the score itself punishes confabulation).
- `seed/suites.json` registers the **`xodexa-frontier-exam`** pack (HLE-class: expert,
  multimodal, closed-ended, held-out private set, ranked by Rank-UB, calibration co-metric).

## 4. Why this is positioned to be the industry standard

A benchmark becomes the standard when it is simultaneously **hard enough to not saturate**
(HLE's contribution), **broad enough to mean "capability" not "trivia"** (Open LLM's
multi-column breadth, extended to 9 categories), **honest enough to expose confident
wrongness** (calibration as a scored metric, not a footnote), and **trustworthy enough that
a number on it can't be faked** (Xodexa's central, cryptographically-verified, contamination-
resistant scoring). The first three exist in pieces across today's boards; the fourth exists
nowhere public. Xodexa AGI Benchmark is the combination.

*Sources analyzed: Scale AI HLE leaderboard & methodology (labs.scale.com), HLE paper
(arXiv:2501.14249), and the Hugging Face Open LLM Leaderboard column/filter design.*
