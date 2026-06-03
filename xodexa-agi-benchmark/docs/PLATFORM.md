# Xodexa AI Benchmark — Live Platform (real LLM benchmarking)

The platform lets a **registered, email-verified** user bring **their own provider API
key**, run a **real benchmark against a real model**, and get a free, signed AGI
Readiness report. Every data point is stored in **Postgres**. The public/live pages
show only real verified runs (empty until they exist); the simulated sample lives
behind the **DEMO** menu and is clearly badged.

## Architecture (all-in-one)
- **`apps/server`** (FastAPI) serves the REST API (`/api/*`), the legacy trust-kernel
  API (`/v1/*`), and the static frontend (`/`) — one origin, one container.
- **Postgres** is the source of truth (SQLAlchemy ORM, portable: SQLite for zero-infra
  dev, Postgres in compose/prod). The app owns the schema via `create_all` on startup.
- **Redis + RQ worker** (`apps/worker`) executes runs asynchronously; the web layer
  enqueues and the UI polls progress. With no Redis (dev) runs execute in a thread.
- Reuses the engine unchanged: `xodexa.generators` → `xodexa.evaluate.score_pack` →
  `xodexa.report.build_report` (signed) → `xodexa.improvement`.

## User flow
1. **Register** (`/register.html`) — username + email + password. A verification email
   is sent (privateemail.com). 2. **Verify** via the emailed link. 3. **Log in**.
4. **Add a provider key** (`/account.html`) — OpenAI / Anthropic / OpenAI-compatible.
   The key is **validated by a live provider call** before it's accepted and stored
   **Fernet-encrypted** (only the last 4 chars are ever shown). 5. **Run** (`/run.html`)
   — pick a saved key (or a one-time key that's never stored), a model, a family (or
   all 12), and task count; watch live progress. 6. **Report** — Xodexa Score (0-1000),
   AGI Readiness level + 10 sub-scores, failure analysis, and a "Path to AGI" roadmap;
   export `.md` for free. View past runs at `/my-reports.html`.

## Legitimacy gates (not a runaway sandbox)
- Only **email-verified** users can add keys or run.
- Keys are **validated against the provider**; model names must be **listed by the
  provider**.
- Per-user **quotas**: max tasks/run (200), max concurrent runs, daily run + task caps
  (all env-configurable), enforced server-side and recorded in `audit_log`.
- CSRF protection on mutations; opaque httpOnly session cookies; auth-route rate limits.

## Security
- Passwords: stdlib `scrypt` (salted). Sessions: random token, only its SHA-256 stored.
- Provider keys: `cryptography.fernet` with `KEY_ENCRYPTION_KEY` (from env/Vault);
  "use once" keys are never persisted (passed to the worker job only).
- Reports are Ed25519-signed; runs keep a hash-chained event log.
- Secrets never appear in logs or API responses.

## Run it
```bash
cp .env.example .env          # set KEY_ENCRYPTION_KEY, SESSION_SECRET, SMTP_PASSWORD
docker compose up --build     # db + redis + server (API+site) + worker
# open http://localhost:8000
```
Generate the secrets:
```bash
python -c "from apps.server.security import generate_fernet_key as g; print(g())"  # KEY_ENCRYPTION_KEY
```
Local dev without Docker (SQLite, inline runs, email links printed to console):
```bash
pip install -r requirements.txt
RUN_INLINE=1 uvicorn apps.server.main:app --reload   # from xodexa-agi-benchmark/
```

## Email (privateemail.com)
Set `SMTP_HOST=mail.privateemail.com`, `SMTP_PORT=465`, `SMTP_USER=info@xodexabenchmark.com`,
`SMTP_PASSWORD=…`, `MAIL_FROM=info@xodexabenchmark.com`, and `PUBLIC_BASE_URL` (used in
verification links — must match the served origin). If `SMTP_PASSWORD` is empty, the
verification link is printed to the server log (dev mode).

## Key endpoints
`POST /api/auth/{register,verify,resend,login,logout}`, `GET /api/auth/me` ·
`GET/POST/DELETE /api/credentials`, `GET/POST/DELETE /api/models` ·
`POST/GET /api/runs`, `GET /api/runs/{id}`, `GET /api/runs/{id}/report[.md]` ·
`GET /api/leaderboard`, `GET /api/dashboard` (live, real runs only).
