# Xodexa-Ω (Xodexa-Omega) Benchmark

**A deliberately brutal, anti-memorization benchmark for large language models.**

Xodexa-Ω is engineered around a single design goal: *make capable models fail*, and
do it **legitimately** — with deterministic, reproducible, auditable scoring rather
than vibes or an LLM judge. It targets the four failure modes that most public
benchmarks reward models for hiding:

1. **Adversarial Reasoning** — false premises, logic traps, and "memorized-answer"
   bait questions that are *almost* the famous version but subtly different.
2. **Long-Context & Memory** — needles, state-tracking, multi-needle aggregation,
   and internal contradictions buried in long, freshly-generated filler.
3. **Hallucination Resistance** — fabricated papers, fake elements, nonexistent API
   methods, impossible studies. The only correct move is honest abstention.
4. **Novel / Unseen Problems** — invented operators, ciphers, sequences, and
   constraint puzzles that cannot be in any training set.

## Why it's hard (and fair)

- **Negative marking.** Confidently-wrong answers and hallucinations score *below
  zero*. Saying "I can't verify that" beats inventing detail. This is the core
  mechanism that fails bluffing models.
- **Trap calibration.** Many items are near-clones of canonical puzzles (Monty Hall,
  bat-and-ball, pound-of-feathers) with one changed assumption that flips the answer.
  Pattern-matching to the memorized solution is explicitly penalized.
- **Anti-memorization by construction.** Every long-context item is *generated at
  run time* from a seed (`--seed`). Change the seed and you get a fresh variant with
  different codes, values, and contradictions. The dataset cannot be memorized.
- **Deterministic grading.** No LLM judge. Every item is graded by exact match,
  numeric tolerance, keyword logic, abstention detection, or false-premise flagging —
  all in `harness.py`, all reproducible.

## Scoring

Each item has positive `points` and, where a confident error is possible, a
`negative` penalty. The final percentage floors negative totals at 0.

| Final % | Tier |
|--------:|------|
| < 10%   | **F** — Fails the benchmark (bluffs, breaks under pressure) |
| 10–25%  | **D** — Brittle |
| 25–40%  | **C** — Competent under adversarial load (a *strong* Xodexa-Ω result) |
| 40–60%  | **B** — Exceptional |
| > 60%   | **A** — Audit for benchmark contamination |

The benchmark is calibrated so that even strong frontier models are expected to land
in the 20–40% band. A score above 60% should be treated as a red flag for leakage,
not a triumph.

## Quick start

```bash
cd xodex_omega

# 1. Verify the harness + every grader, no model or API key needed.
#    Runs a synthetic "oracle" (all-correct -> ~100%), an "adversary"
#    (all-hallucinating -> net negative), and a "silent" run (blank -> 0%).
python3 harness.py selftest

# 2. Export the fully-expanded prompts (long-context items included) to hand to a model.
python3 harness.py export-prompts --out prompts.json

# 3a. Score answers you collected yourself. answers.json is {"AR-01": "model text", ...}
python3 harness.py run --provider manual --answers answers.json --out result.json

# 3b. Or score a model live (needs the relevant key in your environment):
ANTHROPIC_API_KEY=...  python3 harness.py run --provider anthropic --model claude-sonnet-4-6
OPENAI_API_KEY=...     python3 harness.py run --provider openai --model gpt-4o
```

**Important:** if you export prompts for a model, you must score with the **same
`--seed`** you exported with (default `20260602`), so the long-context answer keys
match the prompts the model saw.

## Files

- `dataset.jsonl` — the items. Static items carry their prompt + grader inline;
  long-context items carry a `builder` + `params` and are expanded at run time.
- `harness.py` — loader, long-context builders, deterministic graders, model
  adapters (manual / Anthropic / OpenAI / blank), scoring, and reporting.
- `Xodexa-Omega_Specification.docx` — the formal specification: methodology, item
  catalogue, grader semantics, and calibration rationale.

## Extending it

Add a line to `dataset.jsonl`. Reuse a grader type (`exact`, `numeric`,
`numeric_multi`, `contains_all`, `contains_any`, `flag_false_premise`, `abstain`)
or register a new long-context `builder` in `harness.py`. Re-run `selftest` —
it will confirm an oracle scores 100% and an adversary nets below zero on your new
item before you trust it.
