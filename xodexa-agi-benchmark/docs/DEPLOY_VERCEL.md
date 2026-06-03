# Deploying: Vercel frontend + external backend

**Vercel cannot run this backend.** It needs a long-running FastAPI server, a separate
RQ **worker** process, **Postgres**, and **Redis** — none of which fit Vercel's
serverless model. So the production topology is:

```
Browser ──▶ Vercel (static site)  ──/api, /v1 rewrite──▶  Backend host (Railway/Render/Fly)
                                                           ├─ web    (uvicorn apps.server.main:app)
                                                           ├─ worker (python -m apps.worker.worker)
                                                           ├─ Postgres
                                                           └─ Redis
```

Vercel serves the static UI and **reverse-proxies** every `/api/*` (and `/v1/*`) call to
the backend. Because the browser still talks only to your Vercel domain, the session
cookie + CSRF token are first-party — **no CORS, no cross-site-cookie problems.**

---

## Step 1 — Deploy the backend (example: Railway)

1. New Railway project from this GitHub repo. Add **Postgres** and **Redis** plugins.
2. Create **two services** from the repo (root: `xodexa-agi-benchmark`, Dockerfile
   `apps/server/Dockerfile`):
   - **web** — start command: `uvicorn apps.server.main:app --host 0.0.0.0 --port $PORT`
   - **worker** — start command: `python -m apps.worker.worker`
3. Set these env vars on **both** services (Railway injects `DATABASE_URL` from the
   Postgres plugin — convert the scheme to `postgresql+psycopg://`, and `REDIS_URL`
   from the Redis plugin):

   ```
   DATABASE_URL=postgresql+psycopg://<user>:<pass>@<host>:<port>/<db>
   REDIS_URL=redis://<host>:<port>/0
   KEY_ENCRYPTION_KEY=<run: python -c "from apps.server.security import generate_fernet_key as g; print(g())">
   SESSION_SECRET=<long random string>
   COOKIE_SECURE=true
   PUBLIC_BASE_URL=https://<your-vercel-domain>        # the Vercel URL, NOT the backend URL
   SMTP_HOST=mail.privateemail.com
   SMTP_PORT=465
   SMTP_USER=info@xodexabenchmark.com
   SMTP_PASSWORD=<mailbox password>
   MAIL_FROM=info@xodexabenchmark.com
   ```
   > `PUBLIC_BASE_URL` is the **Vercel** domain on purpose: verification links must point
   > at the public site, which then proxies `/api/auth/verify` back to the backend.
4. Note the backend's public URL, e.g. `https://xodexa-web-production.up.railway.app`.

(Equivalent on Render/Fly: one web service + one worker, plus managed Postgres + Redis,
same env. `docker compose up` reproduces the whole stack locally.)

## Step 2 — Point Vercel at the backend (the rewrite)

Edit `vercel.json` at the repo root and add a `rewrites` block that forwards the API
paths to your backend (replace the host with yours):

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "framework": null,
  "buildCommand": "echo 'static site'",
  "installCommand": "echo 'no deps'",
  "outputDirectory": "xodexa-agi-benchmark/frontend/public",
  "trailingSlash": false,
  "rewrites": [
    { "source": "/api/:path*", "destination": "https://YOUR-BACKEND-HOST/api/:path*" },
    { "source": "/v1/:path*",  "destination": "https://YOUR-BACKEND-HOST/v1/:path*" }
  ]
}
```

Redeploy (push to the branch Vercel tracks, or `vercel --prod`). That's it — the
frontend already calls same-origin `/api` (its default `XODEXA_API_BASE`), so the live
Leaderboard / Dashboard / Reports light up as soon as real runs exist.

## Step 3 — Verify
- `https://<vercel-domain>/api/dashboard` returns JSON (proxied), not 404.
- Register → you receive the verification email (from `info@xodexabenchmark.com`); the
  link is on your Vercel domain and works.
- Log in, add a provider key, run a small benchmark, see the report.

---

## Alternative (no rewrite): point the frontend directly at the backend
If you'd rather not proxy, set the API base on the static site and enable cross-origin
cookies on the backend:
- Frontend: serve a tiny `/config.js` (loaded before `auth.js`) that sets
  `window.XODEXA_API_BASE = "https://YOUR-BACKEND-HOST";`
- Backend: `CORS_ORIGINS=https://<your-vercel-domain>` **and** change the session cookie
  to `SameSite=None; Secure` (cross-site cookies). The rewrite approach avoids both of
  these — prefer it unless you have a reason not to.

## Simplest of all: skip Vercel
Point your domain straight at the backend host. `apps.server.main` already serves the
static site **and** the API from one origin, so no proxy/CORS is involved at all
(`docker compose up`).
```
