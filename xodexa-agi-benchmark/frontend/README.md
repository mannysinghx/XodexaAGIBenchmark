# Xodexa AGI Benchmark — Frontend

Dark, premium research-lab UI (Next.js + TypeScript + Tailwind + shadcn/ui +
Framer Motion + Apache ECharts). The MVP ships a **static, self-contained dashboard**
at `public/dashboard.html` to lock the aesthetic and prove the leaderboard / radar /
badge design; the full Next.js app is Phase 6.

Open the demo directly in a browser:

```bash
open frontend/public/dashboard.html      # macOS
xdg-open frontend/public/dashboard.html  # Linux
```

## Planned routes (Next.js App Router)

```
/                      landing — "the world's most unforgiving open benchmark"
/dashboard             org overview: runs, scores, alerts
/models  /models/new   model registry + connection wizard (OpenAI/Anthropic/vLLM/Ollama/…)
/runners /runners/new  runner registry + keypair registration flow
/benchmarks  /benchmarks/[id]   pack catalogue + detail (categories, layers, versions)
/runs  /runs/[id]      live run monitor + per-task failure matrix
/leaderboard           filterable public leaderboard (verified / attested / open-source / category / cost …)
/compare               head-to-head radar + heatmap
/plugins /plugins/[id] plugin marketplace + detail (permissions, SBOM, signature)
/private-benchmarks    private enterprise eval suites
/reports/[id]          downloadable report (PDF/MD/JSON/CSV/Evals/HELM/Inspect/lm-eval)
/security              verification + attestation + canary/contamination status
/admin                 review queue: suspicious scores, plugin review, canary alerts
/settings  /api-keys   org settings + scoped API keys
```

## Design system
- Background: near-black with a cool radial glow; panels are layered slate gradients.
- Accent `#3da9fc` (signal blue) + `#7c5cff` (violet); status = green/amber/red; gold = attested.
- Components: score cards, radar (category profile), heatmaps (failure matrix), live
  progress monitor, verification + attestation badges, cost/performance charts.
- Charts via **ECharts** (radar/heatmap-heavy UI needs its power over Recharts).
