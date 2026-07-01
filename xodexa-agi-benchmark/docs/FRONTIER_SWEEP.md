# Running a Frontier Baseline Sweep

The sweep is what turns Xodexa from a spec into a benchmark with a real leaderboard.
One command runs a fleet of models over one **fixed-seed** pack (so every model sees
identical items) and emits, in a single JSON artifact:

- a **leaderboard** ranked by accuracy, with each model's IRT ability `θ` and an
  `insufficient` flag when it has fewer than 30 graded items;
- **empirical item difficulty** (CTT pass-rate + 2PL IRT) that replaces hand-assigned
  difficulty;
- an **item-quality** report (which items are too easy / non-discriminating and should
  rotate out);
- **pairwise significance** between all model pairs, FDR-controlled.

Because every model answers the same items, the pairwise tests are valid paired tests
(`stats.mcnemar_exact`), not a comparison of unrelated runs.

## What you provide

Only two things the code can't supply itself:

1. **Provider API keys** — as environment variables named in your models config.
2. **A token budget** — a full sweep is `models × tasks` model calls. Start small
   (e.g. `--n 40`) and scale up once the numbers look sane.

## Config

Copy [`scripts/models.example.json`](../scripts/models.example.json) and edit. Each
entry is `{name, connector, api_key_env}`. Connector specs:

| Spec | Example |
|---|---|
| `openai-compatible:<base>:<model>` | `openai-compatible:https://api.openai.com/v1:gpt-4o` |
| `anthropic:<model>` | `anthropic:claude-sonnet-4-6` |
| `ollama:<base>:<model>` | `ollama:http://localhost:11434:llama3` |
| `sim:<skill>` (offline, no key) | `sim:0.8` — a deterministic persona used for CI/dry-runs |

`api_key_env` names the env var the key is read from (omit for `ollama`/`sim`).

## Run

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...

# One family, 40 items, fixed seed -> paired-comparable:
python scripts/frontier_sweep.py \
  --config scripts/models.json \
  --family reasoning --n 40 --seed 1234 \
  --out results/sweep_reasoning.json
```

Run per family (`reasoning`, `math`, `science`, `code`, `agent`, `multimodal`,
`truthfulness`, `memory`, `instruction_following`, …) and combine. Keep the `--seed`
fixed within a comparison so the paired tests stay valid; vary it across rounds to
resist memorization.

### Dry run (no keys, no spend)

```bash
python scripts/frontier_sweep.py --family reasoning --n 40 --seed 1234
```

With no `--config`, the built-in simulation fleet runs — deterministic personas that
exercise the entire pipeline (grading, IRT, significance) offline. This is also the CI
smoke test.

## Output

Written to `results/` (git-ignored). To publish a leaderboard, feed the artifact's
`leaderboard` array to the live board or the static frontend export. Empirical
difficulty from `item_difficulty` can be written back into the pack via the pipeline's
difficulty stage (`xodexa.irt` → `pipeline._calibrate`).
```
