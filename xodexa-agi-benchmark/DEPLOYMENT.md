# Deploying Xodexa AGI Benchmark — Vercel vs. Railway

**Short answer: use both, for different halves. Frontend on Vercel, the scoring
authority + databases on Railway.** Vercel cannot host the trust kernel; Railway can
host the whole thing if you want a single platform.

---

## Why it splits

Xodexa is two very different workloads (see `ANALYSIS.md`):

| Part | What it needs | Fits Vercel? | Fits Railway? |
|---|---|---|---|
| **Frontend** (Next.js / the Frontier Observatory pages) | static + edge rendering, CDN | **Yes — ideal** | yes |
| **Scoring authority** (FastAPI) | a long-running process that holds the Ed25519 signing key + answer keys in memory, keeps run/nonce state, re-scores centrally, runs background workers | **No** | **Yes — ideal** |
| **Postgres / Redis / object store** | managed, persistent, networked | no (add-ons only) | **Yes — one click** |

Vercel runs **stateless serverless functions** with hard duration limits and no
containers or persistent services — its own docs and guidance say it's not for
background jobs, long-running processes, persistent connections, or stateful services.
Functions cap out around 10 s on the free tier (up to ~60 s with Fluid Compute) and
60–800 s on Pro, with a 500 MB bundle ceiling. That breaks four things Xodexa needs:

1. **The signing key + answer keys must live in a trusted, long-lived process.** On
   serverless, every cold start is a fresh process — you'd be reloading secrets per
   request and you still need an external store for issued-manifest / nonce state.
2. **Central re-scoring and (later) agentic runs exceed function timeouts.**
3. **Background workers (RQ) don't exist on Vercel.**
4. **No persistent DB/Redis connections** — you'd bolt on external services anyway.

Railway, by contrast, builds your `Dockerfile` directly, gives **one-click Postgres,
Redis, and MongoDB** with the connection URL injected as an env var, supports
**private networking between services**, persistent volumes, and cron/worker services —
exactly the multi-service shape this project has. Hobby is **$5/month of usage credit**;
small deployments typically land in the $5–20/month range.

---

## Recommended topology

```
        ┌─────────────────────────┐         ┌──────────────────────────────────┐
        │  VERCEL                  │  HTTPS  │  RAILWAY (one project)            │
        │  • Next.js frontend      │ ──────▶ │  • scoring-authority (FastAPI)    │
        │    (Frontier Observatory)│         │      Dockerfile build             │
        │  • reads NEXT_PUBLIC_API │         │  • postgres  (one-click)          │
        └─────────────────────────┘         │  • redis     (one-click)          │
                                            │  • worker    (RQ, Phase 4)        │
                                            │  • minio / or S3 for bundles      │
                                            └──────────────────────────────────┘
```

Prefer **one platform**? Put everything on **Railway** — it can serve the Next.js
frontend as another service. You only *need* Vercel if you want its best-in-class
frontend DX/CDN. You can **not** collapse onto Vercel-only, because the authority can't
run there.

---

## Railway — deploy the backend (the part that matters)

The repo already ships `apps/server/Dockerfile` and `docker-compose.yml` as the shape.

1. **New Project → Deploy from GitHub repo.** Point the service root at
   `xodexa-agi-benchmark/` and let Railway detect `apps/server/Dockerfile`
   (or set the Dockerfile path explicitly).
2. **Add Postgres** (New → Database → PostgreSQL). Railway injects `DATABASE_URL`.
   Run `db/schema.sql` once (Railway's psql console or a one-off `psql $DATABASE_URL -f db/schema.sql`).
3. **Add Redis** (New → Database → Redis). Injects `REDIS_URL`.
4. **Object storage:** add a MinIO service from a Docker image, **or** point
   `S3_ENDPOINT` at an external S3/R2 bucket for result bundles.
5. **Set the signing key as a Railway variable** (Service → Variables), generated with:
   ```bash
   python -c "from xodexa import KeyPair; k=KeyPair.generate(); print('APEX_SERVER_PRIVATE_KEY='+k.priv_b64); print('APEX_SERVER_PUBLIC_KEY='+k.pub_b64)"
   ```
   Never commit it. (Move to OpenBao/Vault in a hardening pass — see roadmap Phase 5.)
6. **Expose the service** (Settings → Networking → Generate Domain). That URL is your API.
7. Other env vars come from `.env.example` (`BENCHMARK_VERSION`,
   `ALLOWED_RUNNER_VERSIONS`, `MIN_PLAUSIBLE_MS_PER_TASK`, etc.).
8. **Worker (later):** add a second service from the same image with start command
   `rq worker -u $REDIS_URL apex` for long-horizon/agentic runs.

Start command for the API service (already the Dockerfile `CMD`):
`uvicorn apps.server.main:app --host 0.0.0.0 --port $PORT`.

## Vercel — deploy the frontend

The MVP frontend is static HTML (`frontend/public/index.html` etc.); the full Next.js
app is Phase 6. Either way:

1. **Import the repo**, set the project root to `xodexa-agi-benchmark/frontend/`.
2. For the static MVP: no build step — serve `public/` (or drop the HTML into a Next.js
   `app/` route). For the Next.js app: framework preset = Next.js, default build.
3. Set `NEXT_PUBLIC_API_URL` to the Railway service domain so the Observatory's
   `/v1/leaderboard` calls hit the authority.
4. Lock CORS on the FastAPI side to the Vercel domain.

> Note: you *can* run a thin FastAPI read-only endpoint on Vercel's Python runtime for
> demos, but **never the scoring authority** — issuing manifests, holding the signing
> key, and re-scoring must stay on the always-on Railway process.

## Alternatives (same backend shape)

Render, Fly.io, and Northflank all host the container + managed Postgres/Redis just like
Railway if you prefer them; the split (static frontend on a CDN host, stateful authority
on a container host) is the same everywhere.

---

### Sources
- [Vercel Functions — limitations](https://vercel.com/docs/functions/limitations)
- [Using the Python Runtime with Vercel Functions](https://vercel.com/docs/functions/runtimes/python)
- [Can you use Vercel for backend? (Northflank)](https://northflank.com/blog/vercel-backend-limitations)
- [Railway — Deploy a FastAPI App](https://docs.railway.com/guides/fastapi)
- [Railway — Pricing](https://docs.railway.com/pricing)
