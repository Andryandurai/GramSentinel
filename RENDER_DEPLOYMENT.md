# Deploying GramSentinel to Render

This document is specific to this repository as it actually exists — module
names, paths and commands below were read from the code and, where noted,
verified locally by simulating production settings before writing this file.
Anything not actually deployed to Render is marked **NOT VERIFIED**.

---

## 1. Architecture

**Two Render services + one Render PostgreSQL database.** Not a single
combined service.

```
Browser
  |
  +---> Render Static Site   (frontend/, React + Vite build)
  |        gramsentinel-frontend.onrender.com
  |
  +---> Render Web Service   (backend/, Django + DRF, served by Daphne)
           gramsentinel-backend.onrender.com
                |
                +---> Render PostgreSQL
```

**Why split, rather than one Web Service serving both:** Django's built-in
admin site is mounted at `/admin/` (`backend/config/urls.py`). The React
SPA independently uses `/admin/dashboard` as its own Admin Portal client
route (`frontend/src/App.tsx`). If Django served the built SPA directly, a
browser refresh on `/admin/dashboard` would be swallowed by Django's admin
URL resolver — which owns the entire `/admin/` prefix and 404s on any
sub-path it doesn't recognise — instead of reaching `index.html`. Avoiding
that collision by splitting into two services requires zero changes to
either the Django admin URL or any React route, and the codebase already
supports it with no further work:

- The frontend API client (`frontend/src/services/api.ts`) already resolves
  its base URL from `VITE_API_BASE_URL`, with no hardcoded `localhost`
  anywhere in the source.
- The backend already reads `CORS_ALLOWED_ORIGINS` from the environment
  (`django-cors-headers` was already installed and configured).
- Authentication is JWT-bearer (SimpleJWT), stored in `localStorage` and
  sent as an `Authorization` header — not a cookie — so a cross-origin
  frontend/backend split has no session-cookie complications for the API.
  (The Django admin panel itself *does* use session + CSRF cookies, but
  that is same-origin, entirely on the backend service, and unaffected by
  the split.)

This is the "simplest architecture that preserves current functionality"
called for — it needed no application code changes, only deployment
configuration.

---

## 2. Prerequisites

- A Git provider (GitHub/GitLab/Bitbucket) with this repository pushed.
- A Render account.
- Nothing else — no Redis, no external services. The LLM integration is
  optional and the platform is fully functional with it disabled.

## 3. Repository requirements

- `requirements.txt` at the repo root (already present).
- `backend/manage.py`, `backend/config/{settings,urls,wsgi,asgi}.py`
  (already present, module name is `config`).
- `frontend/package.json` with a `build` script producing `frontend/dist`
  (already present).
- `backend/.python-version` (`3.11.9`) and `frontend/.nvmrc` (`20`) — added
  as part of this hardening pass so Render's native runtimes pin the same
  versions verified locally.

---

## 4–10. Service definitions

### Backend — Render Web Service

| Field | Value |
|---|---|
| Runtime | Python |
| Root Directory | `backend` |
| Build Command | `pip install --upgrade pip && pip install -r ../requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate` |
| Start Command | `daphne -b 0.0.0.0 -p $PORT config.asgi:application` |
| Health Check Path | `/api/health/` |

`requirements.txt` is one directory above `backend/` (repo root), hence
`../requirements.txt` — Render runs build/start commands with the Root
Directory as the working directory.

**Why Daphne (ASGI) and not Gunicorn (WSGI) for the start command**, even
though `gunicorn` is also a dependency: this project's officer dashboard has
an optional WebSocket push (`backend/alerts/consumers.py`,
`backend/alerts/routing.py`, wired through `backend/config/asgi.py`) that
only works over ASGI. It is explicitly best-effort by design — the officer
dashboard is fully functional on REST polling alone if the socket never
connects — but Daphne is already a dependency and needs no extra
infrastructure (the channel layer is `InMemoryChannelLayer`, which needs no
Redis and is correct for Render's default single-instance web service), so
there is no reason to give up that feature for a Render deployment. The
existing `docker-compose.yml` / `docker/Dockerfile.backend` path (which
does use `gunicorn` + WSGI) was left untouched — this Daphne choice is
specific to the Render start command documented here, not a change to that
file.

### Frontend — Render Static Site

| Field | Value |
|---|---|
| Root Directory | `frontend` |
| Build Command | `npm install && npm run build` |
| Publish Directory | `dist` |
| Rewrite rule | Source `/*` → Destination `/index.html` (Action: Rewrite) |

Add the rewrite rule under the Static Site's **Redirects/Rewrites** tab.
Without it, refreshing any client-side route (`/worker/dashboard`,
`/officer/community-data`, `/admin/dashboard`, etc.) 404s instead of
loading the SPA, which then handles that route itself via React Router.

### Database — Render PostgreSQL

Create it first (see step-by-step below), then attach its **Internal
Database URL** to the backend service as `DATABASE_URL`. No manual
connection-string assembly needed if you use Render's "Add from Database"
env var picker (or `render.yaml`'s `fromDatabase`), which supplies it
directly.

---

## 11. Health check endpoint

`GET /api/health/` (already implemented, unmodified — `backend/config/urls.py`).

```json
{
  "service": "GramSentinel",
  "description": "Rural Healthcare Intelligence & Community Early-Warning Platform",
  "status": "ok",
  "data_notice": "Prototype. Synthetic / public / anonymised data only.",
  "disclaimer": "Decision-support only. Does not replace professional medical care. Human approval required."
}
```

No authentication, no database query, no secrets. Verified locally under
simulated production settings (`DEBUG=False`, Render proxy headers) to
return `200` with the security headers (`Strict-Transport-Security`,
`X-Content-Type-Options`, etc.) correctly attached. This is the pre-existing
endpoint — a second `/health/` path was deliberately **not** added, since
this one already satisfies every requirement and adding a duplicate would
be an unrelated change.

## 12. Environment variables

### Required

| Variable | Value | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | Render-generated | Use Render's "Generate Value" — never reuse the local dev placeholder |
| `DEBUG` | `False` | |
| `DATABASE_URL` | From the Postgres service | Use Render's "Add from Database" picker |
| `PYTHON_VERSION` | `3.11.9` | Matches `backend/.python-version` |
| `CORS_ALLOWED_ORIGINS` | `https://<frontend-service>.onrender.com` | The frontend Static Site's exact URL |
| `VITE_API_BASE_URL` (frontend service) | `https://<backend-service>.onrender.com/api` | Build-time only — see note below |

`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` do **not** need to be set by
hand: `backend/config/settings.py` reads Render's own
`RENDER_EXTERNAL_HOSTNAME` variable (which Render injects into every web
service automatically) and adds it to both automatically. Only set these
explicitly if you attach a custom domain.

### Optional

| Variable | Default | Notes |
|---|---|---|
| `SECURE_HSTS_SECONDS` | `3600` | Starts conservative; raise once HTTPS is confirmed end-to-end |
| `DB_CONN_MAX_AGE` | `60` | Postgres connection reuse, seconds |
| `DATABASE_SSL_REQUIRE` | `False` | Render's internal DB URL doesn't need this; set `True` only if you connect via the external URL |
| `LLM_ENABLED` | `False` | Platform is fully functional without it |
| `LLM_API_KEY` | *(empty)* | Mark "sync: false" / secret in Render — never commit |
| `TIME_ZONE` | `Asia/Kolkata` | |
| `GRAMSENTINEL_LOG_LEVEL` | `INFO` | |
| `ALLOWED_HOSTS` | auto | Only for a custom domain |
| `CSRF_TRUSTED_ORIGINS` | auto | Only for a custom domain |

**`VITE_API_BASE_URL` is a build-time variable**, baked into the compiled
JS bundle by Vite when the Static Site builds — it is not read at request
time. If you change it, you must trigger a new frontend build (a redeploy),
not just update the env var. This was verified locally: building with
`VITE_API_BASE_URL=https://gramsentinel-backend.onrender.com/api npm run
build` produces a bundle containing that literal string.

**Ordering note:** the two service URLs (`https://gramsentinel-backend
.onrender.com`, `https://gramsentinel-frontend.onrender.com`) are
predictable from the service *name* as soon as you create each service —
you don't need to wait for a build to finish to know a service's URL. The
practical order is: create both services (reserving their names/URLs) →
set `CORS_ALLOWED_ORIGINS` on the backend and `VITE_API_BASE_URL` on the
frontend using each other's known URLs → deploy both.

## 13. Static files

Already production-ready, unmodified: WhiteNoise is in `MIDDLEWARE`,
`STATIC_ROOT`/`STATIC_URL` are configured, and `STORAGES["staticfiles"]`
uses `whitenoise.storage.CompressedStaticFilesStorage`. `collectstatic`
was verified locally (162 files copied, 152 post-processed, zero errors)
under `DEBUG=False`. This only serves Django's own admin/DRF assets — the
React SPA is served entirely by the separate Static Site, not by Django.

## 14. Media / file upload considerations

**No `MEDIA_ROOT` exists in this project, and none is needed.** The one
file-upload feature — staff profile photographs
(`backend/users/photos.py`, `User.photo` on `backend/users/models.py`) —
stores the image as a validated base64 data URI directly on the user
record in the database, not on the filesystem. It is served only through
the authenticated, village-scoped profile endpoints, never from a public
media URL. This sidesteps Render's ephemeral filesystem entirely: there is
no uploaded file to lose on a redeploy, because nothing is ever written to
disk. Upload validation (`backend/users/photos.py`) already enforces file
type (PNG/JPEG/WebP, checked by decoding and verifying the real magic
bytes — not just the claimed MIME type), a 1.5 MB size ceiling, and rejects
anything that fails to decode.

## 15. WebSockets / Django Channels

Used, but explicitly optional by design (see section 4–10 above for the
Daphne rationale). `CHANNEL_LAYERS` uses `InMemoryChannelLayer` — correct
for Render's default single-instance web service, and no Redis is
provisioned or required. **Known limitation:** if this service is ever
scaled to more than one instance, `InMemoryChannelLayer` will not
broadcast a WebSocket push across instances (each instance only knows
about its own connections). That is out of scope for this hardening pass
— document it, don't fix it, since the feature already degrades
gracefully to polling and the task scope is a single-instance Render
deployment.

## 16. Error handling

Already implemented, unmodified: `backend/config/exceptions.py` gives
every DRF exception a uniform `{"error": true, "detail": ..., "status_code":
...}` envelope, and `DEBUG=False` means Django's own debug pages (stack
traces, settings dump) never render — unhandled exceptions return a plain
500 with nothing sensitive in the body. Verified: `DEBUG=False` is honoured
correctly in the production simulation (see section 17).

## 17. AI / multi-agent production safety

Unmodified by this hardening pass. The six-stage pipeline
(`backend/agents/`, `backend/safety/`) and its independence from the LLM
were not touched — this was a deployment-configuration task, not an
application change. The deterministic safety engine
(`backend/safety/engine.py`) has no import of, or dependency on, the LLM
client; the LLM (`backend/agents/llm_client.py` equivalent) is used only
for narrative rewording and is optional (`LLM_ENABLED=False` by default —
the platform runs on deterministic logic alone with no key configured).

## 18. Synthetic demo data / demo accounts

`python manage.py seed_demo` (idempotent — re-running does not duplicate
records, per its own docstring in
`backend/core/management/commands/seed_demo.py`) creates the three-village
demonstration scenario and its accounts (`worker.a`/`officer.a` for
Village A, `worker.b`/`officer.b` for Village B, `worker.c`/`officer.c` for
Village C, plus `patient`, `admin`, and the original `worker`/`officer`
accounts — all password `demo1234`, all synthetic data only).

**This is intentionally not part of the build command.** Run it once, by
hand, after the first successful deploy, via Render's Shell tab:

```
python manage.py seed_demo
```

All accounts and data are clearly synthetic (see the medical/data
disclaimers already present throughout the app and API responses). These
demo credentials are for the hackathon demonstration only and must be
removed or changed before any real deployment handling real people's data.

---

## 19. First deployment steps

See **STEP-BY-STEP RENDER DEPLOYMENT** at the end of this document.

## 20–22. Verifying a deployment

1. `curl https://<backend>.onrender.com/api/health/` → `200`, `"status":
   "ok"`.
2. Open `https://<frontend>.onrender.com/login` → the login page renders
   (not a blank page or a 404 — confirms the rewrite rule is working).
3. Sign in as `officer.a` / `demo1234` → the Officer Portal loads with
   seeded village data (confirms `DATABASE_URL`, migrations, and
   `seed_demo` all worked).
4. Refresh the browser on a deep route, e.g.
   `https://<frontend>.onrender.com/officer/community-data` → it must
   still load the SPA, not 404 (confirms the rewrite rule specifically,
   as opposed to just the root `/` working).
5. `https://<backend>.onrender.com/admin/` → Django admin login page loads
   over HTTPS with no CSRF error on submission (confirms
   `CSRF_TRUSTED_ORIGINS` auto-derivation).

## 23. How to redeploy

Push to the connected branch — Render redeploys automatically by default
(or trigger **Manual Deploy → Deploy latest commit** from each service's
dashboard). A frontend-only content change still needs a frontend
redeploy even if the backend didn't change (static builds don't
auto-invalidate). Changing `VITE_API_BASE_URL` requires a frontend
redeploy specifically (it's baked in at build time — see section 12).

## 24. Viewing logs

Each service's Render dashboard page → **Logs** tab (live tail) or
**Events** tab (deploy history). The custom `gramsentinel` logger
(`backend/config/settings.py` → `LOGGING`) writes to stdout, which Render
captures automatically — no extra configuration needed.

## 25. Updating environment variables

Service dashboard → **Environment** tab → edit → **Save Changes**. Render
automatically redeploys the service after an env var change (this
includes the frontend, whose `VITE_API_BASE_URL` needs an actual rebuild,
not just a process restart — the automatic redeploy Render triggers on
env var save handles this correctly since it reruns the build command).

## 26. Security notes

- No secret is committed anywhere in this repository — see the audit
  table in this hardening pass's final report.
- `DJANGO_SECRET_KEY` must be Render-generated or otherwise random per
  environment; never reuse the local dev fallback value from
  `backend/config/settings.py`.
- `CORS_ALLOW_ALL_ORIGINS` is not used, and `ALLOWED_HOSTS = ["*"]` is not
  used — both are explicit, env-driven allowlists.
- `DEBUG` must be `False` in production; the local fallback default is
  `True` specifically so local development needs no `.env` file at all,
  and it is the deploying operator's responsibility to set `DEBUG=False`
  as a Render environment variable (this cannot be forced from inside the
  settings file without breaking local development, which the task
  explicitly prohibits).
- Demo accounts (`demo1234`) are synthetic-only and documented as such
  on the login page itself; they are not a production credential and
  must not be treated as one.

## 27. Production limitations (honest, not hidden)

- **Single-instance assumption.** `InMemoryChannelLayer` (WebSocket push)
  and the free-tier Render Postgres/web-service plans are both
  single-instance. Horizontal scaling would need a Redis channel layer
  and a paid Postgres plan; out of scope here.
- **Render free-tier cold starts.** A free Web Service spins down after
  inactivity and takes tens of seconds to wake on the next request — the
  health check will fail during that window. Fine for a hackathon demo;
  document it so it isn't mistaken for a real outage.
- **HSTS starts at 1 hour, not preloaded.** Deliberately conservative
  (see section 12); raise `SECURE_HSTS_SECONDS` once HTTPS is confirmed
  stable, per Django's own guidance on not enabling HSTS carelessly.
- **`manage.py check --deploy` reports two remaining warnings** —
  `security.W005` (HSTS include-subdomains) and `security.W021` (HSTS
  preload) — left off deliberately. Both are effectively one-way
  commitments (preload submission in particular is very hard to reverse)
  and this app owns no subdomains that need the include-subdomains
  behaviour. Verified locally: with `DEBUG=False` and a real-length
  secret key, this is the *only* remaining `check --deploy` output; every
  other production-safety warning is resolved.
- **This render.yaml has not been run against a live Render deployment**
  (no Render API access in this environment) — it was written to Render's
  documented Blueprint spec but is marked NOT VERIFIED; the manual
  dashboard steps below are the authoritative path.

## 28. Future improvements (not done, out of scope for this pass)

- Redis-backed channel layer if the backend is ever scaled to multiple
  instances.
- `whitenoise.storage.CompressedManifestStaticFilesStorage` for
  cache-busted static assets (currently `CompressedStaticFilesStorage` —
  works fine, just without far-future cache headers on hashed filenames;
  left unchanged since it already works and touching it risks the DRF
  browsable-API assets for no benefit to this app's actual users, who
  never hit Django's static files at all).
- Frontend bundle code-splitting (Vite's own build already warns that the
  673 KB main chunk exceeds its default 500 KB advisory threshold — a
  pre-existing, non-blocking warning, not introduced by this pass and not
  fixed by it, since it's a performance nicety unrelated to deployment
  readiness).

---

# RENDER DEPLOYMENT INFORMATION

Exact values for the Render dashboard.

```
SERVICE TYPE:
Web Service (backend) + Static Site (frontend)

REPOSITORY:
This Git repository, pushed to GitHub/GitLab/Bitbucket

BRANCH:
main

--- BACKEND WEB SERVICE ---

ROOT DIRECTORY:
backend

RUNTIME:
Python 3

BUILD COMMAND:
pip install --upgrade pip && pip install -r ../requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate

START COMMAND:
daphne -b 0.0.0.0 -p $PORT config.asgi:application

HEALTH CHECK PATH:
/api/health/

DATABASE:
Render PostgreSQL (attach via DATABASE_URL)

ENVIRONMENT VARIABLES (backend):
DJANGO_SECRET_KEY=<Generate in Render>
DEBUG=False
PYTHON_VERSION=3.11.9
DATABASE_URL=<Add from Database — Render PostgreSQL internal connection string>
ALLOWED_HOSTS=<leave unset — auto-derived from Render's RENDER_EXTERNAL_HOSTNAME>
CSRF_TRUSTED_ORIGINS=<leave unset — auto-derived from Render's RENDER_EXTERNAL_HOSTNAME>
CORS_ALLOWED_ORIGINS=https://<your-frontend-service-name>.onrender.com
SECURE_HSTS_SECONDS=3600
DB_CONN_MAX_AGE=60
DATABASE_SSL_REQUIRE=False
LLM_ENABLED=False
LLM_API_KEY=
TIME_ZONE=Asia/Kolkata
GRAMSENTINEL_LOG_LEVEL=INFO

--- FRONTEND STATIC SITE ---

ROOT DIRECTORY:
frontend

BUILD COMMAND:
npm install && npm run build

PUBLISH DIRECTORY:
dist

ENVIRONMENT VARIABLES (frontend):
NODE_VERSION=20
VITE_API_BASE_URL=https://<your-backend-service-name>.onrender.com/api

REDIRECTS/REWRITES (frontend):
Source: /*
Destination: /index.html
Action: Rewrite
```

---

# STEP-BY-STEP RENDER DEPLOYMENT

1. Push this repository to GitHub (or GitLab/Bitbucket).
2. In Render: **New → PostgreSQL**. Name it (e.g. `gramsentinel-db`),
   choose the Free plan, create it. Wait for it to become **Available**.
3. **New → Web Service**, connect this repository.
4. Select the `main` branch.
5. Root Directory: `backend`.
6. Build Command:
   `pip install --upgrade pip && pip install -r ../requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
7. Start Command:
   `daphne -b 0.0.0.0 -p $PORT config.asgi:application`
8. Add the backend environment variables listed above. For
   `DATABASE_URL`, use the "Add from Database" picker and select the
   Postgres instance from step 2 (this fills in the correct connection
   string automatically — do not type it by hand). For
   `DJANGO_SECRET_KEY`, use "Generate Value".
9. Health Check Path: `/api/health/`.
10. Create the service. Note its URL, e.g.
    `https://gramsentinel-backend.onrender.com` (visible immediately,
    before the build even finishes).
11. **New → Static Site**, connect the same repository.
12. Root Directory: `frontend`. Build Command: `npm install && npm run
    build`. Publish Directory: `dist`.
13. Add `VITE_API_BASE_URL` = the backend URL from step 10 + `/api`, and
    `NODE_VERSION` = `20`.
14. Under **Redirects/Rewrites**, add: Source `/*` → Destination
    `/index.html` → Action Rewrite.
15. Create the site. Note its URL, e.g.
    `https://gramsentinel-frontend.onrender.com`.
16. Go back to the **backend** service → Environment → set
    `CORS_ALLOWED_ORIGINS` to the frontend URL from step 15 → save
    (triggers an automatic redeploy).
17. Watch the backend's build logs; confirm `collectstatic` and
    `migrate` both complete without error.
18. Watch the frontend's build logs; confirm `vite build` completes and
    the bundle references your real backend URL (it does, since
    `VITE_API_BASE_URL` was set before this build started).
19. Open the backend's Shell tab and run: `python manage.py seed_demo`
    — this creates the demo villages, accounts and synthetic data
    (idempotent; safe to re-run).
20. Open the frontend URL. Confirm the login page renders.
21. Sign in as `worker.a` / `demo1234` → confirm the Worker Portal loads
    with Village A data.
22. Sign in as `officer.a` / `demo1234` → confirm the Officer Portal,
    Community Data tab, and Alerts all load.
23. Sign in as `patient` / `demo1234` → confirm the Patient Portal loads
    and shows only that patient's own data.
24. Sign in as `admin` / `demo1234` → confirm the Admin Portal loads with
    the platform-wide overview and village filter.
25. Confirm AI/agent functionality: submit a new assessment as a worker
    and confirm the triage support, agent handoffs, and safety-check
    sections render (this exercises the full six-stage pipeline).
26. `curl https://<backend>.onrender.com/api/health/` → confirm `200`
    and `"status": "ok"`.
27. Record both final Render URLs for future reference.

---

# TROUBLESHOOTING

| Symptom | Likely cause | Fix |
|---|---|---|
| Build fails: `ModuleNotFoundError` | A dependency is missing from `requirements.txt`, or the build command's `pip install` path is wrong | Confirm Root Directory is `backend` and the build command reads `../requirements.txt` (one level up) |
| `DisallowedHost` error on every request | `RENDER_EXTERNAL_HOSTNAME` wasn't picked up (unlikely — Render sets it automatically) or you're using a custom domain | Add the exact hostname to `ALLOWED_HOSTS` explicitly as an env var |
| Browser console: CORS error, request blocked | `CORS_ALLOWED_ORIGINS` on the backend doesn't exactly match the frontend's URL (scheme + host, no trailing slash) | Set it to the exact `https://...onrender.com` origin, redeploy the backend |
| Django admin login: "CSRF verification failed" | `CSRF_TRUSTED_ORIGINS` doesn't include the backend's own origin, or `SECURE_PROXY_SSL_HEADER` isn't honouring Render's proxy | Confirm `RENDER_EXTERNAL_HOSTNAME` is set (automatic); for a custom domain, set `CSRF_TRUSTED_ORIGINS` explicitly |
| Refreshing `/officer/dashboard` (or any deep link) gives a 404 | Missing SPA rewrite rule on the Static Site | Add Source `/*` → Destination `/index.html` → Rewrite under Redirects/Rewrites |
| Static files (Django admin CSS) missing / unstyled admin page | `collectstatic` didn't run, or ran before `DEBUG`/`STATIC_ROOT` were correctly set | Confirm the build command includes `python manage.py collectstatic --noinput` and check the build log for its "N static files copied" line |
| Database connection errors on first deploy | `DATABASE_URL` wasn't set, or was typed by hand incorrectly | Use Render's "Add from Database" picker, not a hand-typed string |
| Migration errors | A genuinely new/incompatible migration, not something this pass introduces (no migrations were added or changed in this pass) | Check the specific migration in the build log; this project's existing migrations were verified locally against both SQLite and a parsed Postgres config before this document was written |
| `VITE_API_BASE_URL` seems ignored — frontend still calls the wrong backend | It's a build-time variable; changing it without rebuilding does nothing | Trigger a new frontend build/deploy after changing it |
| JWT auth fails right after login / immediate 401 | Clock skew, or the access token lifetime (12h) already expired on an old cached token | Clear `localStorage` (`gs.access`/`gs.refresh` keys) and log in again |
| WebSocket connection failures in the officer dashboard | Expected/harmless — this is a best-effort enhancement (see section 15); confirm the dashboard's data still loads via REST | No fix needed unless you specifically require live push; see section 27's scaling note |
| LLM-related errors in logs | `LLM_ENABLED=True` with no/invalid `LLM_API_KEY` | Either set a valid key or leave `LLM_ENABLED=False` — every agent has a deterministic fallback and the app is fully functional either way |
| Render port binding failure | Start command doesn't bind `0.0.0.0` or doesn't use `$PORT` | Use the exact start command given above — both are already correct in it |
| Frontend build fails: TypeScript errors | Unlikely from this pass (verified locally: `npm run build` — which runs `tsc -b && vite build` — passes clean) | If it happens on Render specifically, confirm `NODE_VERSION=20` is set; a much older/newer Node can behave differently |
