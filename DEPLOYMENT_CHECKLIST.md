# GramSentinel — Render Deployment Checklist

Full rationale for each item lives in `RENDER_DEPLOYMENT.md`. This is the
quick pre-flight/post-flight list.

## Pre-deployment (repository)

- [x] Repository pushed to Git — *your action; not verifiable from here*
- [x] Production dependencies added (`dj-database-url`, `psycopg[binary]`)
      and installed/verified locally
- [x] `.env.example` created and kept in sync with every variable
      `backend/config/settings.py` actually reads
- [x] Secrets audited — none committed (see security audit in the final
      report; `.env` confirmed gitignored and contains no real secret)
- [x] `DEBUG=False` path implemented and verified (gated correctly; local
      dev unaffected since it defaults to `True` only locally)
- [x] `ALLOWED_HOSTS` supports Render (`RENDER_EXTERNAL_HOSTNAME`
      auto-added)
- [x] `CSRF_TRUSTED_ORIGINS` configured (auto-derived from
      `RENDER_EXTERNAL_HOSTNAME`, plus manual override via env var)
- [x] `CORS_ALLOWED_ORIGINS` configured (pre-existing, env-driven; no
      wildcard)
- [x] PostgreSQL configured (`DATABASE_URL` via `dj-database-url`,
      restricted to `postgres://`/`postgresql://` schemes; SQLite untouched
      as the local default)
- [x] Migrations verified (`makemigrations --check --dry-run` → "No
      changes detected"; `migrate --plan` runs clean against both SQLite
      and a parsed Postgres config)
- [x] Static files configured (WhiteNoise — pre-existing; `collectstatic`
      verified: 162 files copied, 0 errors, under `DEBUG=False`)
- [x] React production build verified (`npm run build` succeeds; bundle
      confirmed to embed `VITE_API_BASE_URL` at build time)
- [x] API URL configuration verified (frontend has zero hardcoded
      `localhost`; fully env-driven, pre-existing)
- [x] Authentication verified locally under production settings (JWT
      login, Django admin session/CSRF login both returned `200` against
      a Daphne server running with `DEBUG=False` and Render-style proxy
      headers)
- [x] Health endpoint verified (`/api/health/` → `200`, no auth, correct
      security headers present)
- [x] Demo data seeding mechanism confirmed idempotent
      (`python manage.py seed_demo`); confirmed **not** wired into the
      build command
- [x] Render Blueprint (`render.yaml`) created — marked NOT VERIFIED
      against a live deployment; manual dashboard path is authoritative
- [ ] Render environment variables configured — *done in the Render
      dashboard during actual deployment, not from this repository*
- [ ] Build command verified **on Render** — *NOT VERIFIED; verified
      locally only, see final report*
- [ ] Start command verified **on Render** — *NOT VERIFIED; verified
      locally only (Daphne booted, served `/api/health/` and
      `/admin/login/` correctly under simulated production settings)*
- [ ] Production checks passed **on Render** — *NOT VERIFIED; local
      `check --deploy` simulation passed with only the two deliberately
      deferred HSTS warnings*
- [ ] Deployment verified **on Render** — *NOT VERIFIED; no live Render
      deployment was performed in this session*

## First deployment (in the Render dashboard)

- [ ] PostgreSQL database created, status **Available**
- [ ] Backend Web Service created (Root Directory `backend`)
- [ ] Backend build command set exactly as documented
- [ ] Backend start command set exactly as documented
- [ ] Backend env vars set (`DJANGO_SECRET_KEY` generated, `DEBUG=False`,
      `DATABASE_URL` from the "Add from Database" picker, `PYTHON_VERSION`,
      `CORS_ALLOWED_ORIGINS`)
- [ ] Backend health check path set to `/api/health/`
- [ ] Backend deployed; build log shows `collectstatic` and `migrate`
      both completing without error
- [ ] Frontend Static Site created (Root Directory `frontend`)
- [ ] Frontend build/publish settings set exactly as documented
- [ ] Frontend `VITE_API_BASE_URL` set to the backend's real URL + `/api`
- [ ] Frontend SPA rewrite rule added (`/*` → `/index.html`, Rewrite)
- [ ] Frontend deployed
- [ ] Backend `CORS_ALLOWED_ORIGINS` updated to the frontend's real URL,
      redeployed
- [ ] `python manage.py seed_demo` run once via the backend's Shell tab

## Post-deployment verification

- [ ] `GET /api/health/` returns `200`
- [ ] Frontend login page loads at the root URL
- [ ] Refreshing a deep client route (e.g. `/officer/community-data`)
      does **not** 404
- [ ] `worker.a` / `demo1234` logs in, Worker Portal loads with Village A
      data
- [ ] `officer.a` / `demo1234` logs in, Officer Portal + Community Data +
      Alerts all load
- [ ] `patient` / `demo1234` logs in, Patient Portal loads, shows only
      that patient's own data
- [ ] `admin` / `demo1234` logs in, Admin Portal loads with the
      platform-wide overview and village filter
- [ ] Submitting a new assessment shows triage support, agent handoffs,
      and a safety-check result (full pipeline exercised end to end)
- [ ] Django admin (`/admin/`) login works over HTTPS with no CSRF error
- [ ] No stack trace, secret, or internal path appears in any error
      response (spot-check a deliberately invalid request)

## Ongoing

- [ ] `SECURE_HSTS_SECONDS` raised beyond the initial 1-hour default once
      HTTPS is confirmed stable across a few days
- [ ] Demo credentials rotated or removed before any real (non-synthetic)
      data is ever entered into this deployment
