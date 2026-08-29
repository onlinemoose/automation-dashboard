# Deployment checklist — Render

Living to-do for getting this app online and growing it. Tick items as
they're done; keep the dated notes at the bottom. The generic serving
details (env vars, reverse proxy, systemd) are in `DEPLOY.md`; this file
is the Render-specific plan and the running task list.

## Decision

**Host: Render — free web service.** Chosen over Railway (usage-metered,
bill less predictable) and Fly.io (cheapest, but its 60s idle-connection
close is a hazard for our silent 30–60s letter POST, and it's more
hands-on). Render gives the "connect the repo, auto-deploy on push" flow,
no request-timeout gotcha, and a managed Postgres we can add later.

The free web service is 512 MB / 0.1 CPU and **spins down after 15 min
idle**, then takes ~30–60s to answer the first request while it wakes.
Accepted for early internal use. Upgrading to Starter ($7/mo) later is a
one-line `plan:` change in `render.yaml` and removes the spin-down —
nothing else changes.

---

## Phase 1 — First deploy — DONE (2026-08-29)

**Live:** https://automation-dashboard-r9i7.onrender.com — Render free plan.

- [x] Create a Render account, connect the GitHub repo
      (`onlinemoose/automation-dashboard`).
- [x] New Web Service, region chosen. Region can't be changed later
      without recreating the service.
- [x] Build command: `git config --global url."https://${GH_TOKEN}@github.com/".insteadOf "https://github.com/" && uv sync --frozen --no-dev && uv cache prune --ci`
- [x] Start command:
      `uv run --no-sync uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT`
- [x] Compute: **Free**.
- [x] Health Check Path: `/health`. Auto-deploy on `main`: on (confirmed
      — the threadpool fix deployed on push).
- [x] **Private capability repo** (`cover-letter-writer`): fine-grained
      GitHub PAT (Contents: Read-only) as env var `GH_TOKEN` + the
      `git config … insteadOf` prefix in the build command. **PAT expires
      ≤1 year — rotating it is a recurring task** (same build error
      returns when it lapses).
- [x] Secret env vars set by hand: `SESSION_SECRET` (fresh, via Render's
      Generate), `DASHBOARD_PASSWORD_HASH`, `ANTHROPIC_API_KEY`,
      `GH_TOKEN`. `DASHBOARD_HTTPS=1`.
- [x] `DASHBOARD_STUB_RUNS` unset (confirmed — a real letter generated,
      no stub banner).
- [x] Smoke test: `/health` 200; `/` → `/login`; login works; real
      cover-letter run returns a letter; `/static/app.css` 200 `text/css`.
- [x] Threadpool fix for the blocking `run()` (commit `90e4696`) — first
      real run 502'd on assets until this landed. See Log below.
- [x] `docs/PROGRESS.md` entry.

### Still open (not blocking)

- [x] Pin Python: `.python-version` = `3.12` at the repo root.
- [x] `render.yaml` at the repo root — reference copy of the service
      config (the live service was made by hand; the file doesn't bind it
      retroactively).
- [x] `dashboard/__main__.py` reads `PORT` (and binds `0.0.0.0` when it's
      set), so `uv run dashboard` also works as a platform start command.
- [x] Download `.md` links confirmed working on the live site.
- [ ] Render dashboard → service → Settings → **Ignored Paths**: add
      `docs/**` so doc-only commits don't trigger a redeploy. (Manual —
      dashboard only.)
- [ ] (Optional) Custom domain in Render (free plan supports it + auto
      TLS). `DASHBOARD_HTTPS` is already `1`.

### Optional cleanup

- [ ] Make `dashboard/__main__.py` read `PORT` as a fallback
      (`os.environ.get("DASHBOARD_PORT") or os.environ.get("PORT")`) so
      `uv run dashboard` works as the start command too. Not required if
      the start command calls `uvicorn` directly (template below does).

---

## Phase 2 — Multi-user auth (Option B, not built yet)

A shared password ships fine for a handful of trusted people. When more
than one named person needs access and individual revocation:

- [ ] Extend `dashboard/_auth.py`: read `DASHBOARD_USERS` as
      `"name:scrypt$…,name:scrypt$…"`, verify `username` + `password`.
- [ ] Add a `username` field to `templates/login.html`.
- [ ] Add a `hashpw` mode that prints a `name:hash` line ready to paste.
- [ ] Document the `DASHBOARD_USERS` format in `docs/` (rule 6: the
      app's storage is written up here).
- [ ] `.env.example` + Render env var.
- [ ] Tests in `tests/test_auth.py` for the multi-user path.

No database, no dependency — a list of hashes in one env var. Portable to
any host if we ever move.

---

## Phase 3 — Real accounts + database (future)

Triggered when we save data against a user (saved drafts, history, a
linked calendar). This replaces Phase 2, doesn't extend it.

- [ ] Add `fastapi-users` + `sqlmodel` (or `sqlalchemy`) — a library, not
      a framework; the FastAPI app is untouched structurally.
- [ ] Postgres: **Neon** or **Supabase** free tier (more generous and
      longer-lived than Render's free Postgres) — just a connection
      string in the env. Or SQLite on a Render persistent disk if we stay
      single-instance.
- [ ] "Sign in with Google" via Authlib (we'll be doing Google OAuth for
      any calendar feature anyway; reuse it for login).
- [ ] `dashboard/_auth.py` is the swap point — page code doesn't change.
- [ ] Backups on from day one (losing the DB = everyone re-links).
- [ ] If we ever run 2+ app instances, SQLite-on-disk breaks — that's the
      move to Postgres.

---

## Phase 4 — Calendar feature (future, design not fixed)

Leading option: **screenshot + vision model**, no calendar OAuth.

- [ ] Capability module: `(week screenshot, our availability, their
      timezone) -> suggested slots`. Its own repo, pinned like
      `cover-letter-writer`.
- [ ] Page: image upload + timezone field + "confirm what we read" step
      before suggesting times.
- [ ] Alternative/additional input mode: paste a private ICS URL (one
      parser, all providers, no app registration) — a stored ICS URL is a
      bearer secret, so encrypt at rest or don't store it.
- [ ] Our own calendar: hard-wired config (an availability spec, or our
      own published ICS URL).

Avoid per-provider OAuth (Google + Microsoft + Apple = three
integrations, and Apple has no clean API path).

---

## Reference

### Environment variables on Render

| Variable | Value | Where |
|---|---|---|
| `SESSION_SECRET` | fresh `secrets.token_urlsafe(32)` — **not** the local one | dashboard (secret) |
| `DASHBOARD_PASSWORD_HASH` | `uv run python -m dashboard.hashpw` | dashboard (secret) |
| `ANTHROPIC_API_KEY` | the real key | dashboard (secret) |
| `GH_TOKEN` | fine-grained PAT, read-only Contents on the private capability repos | dashboard (secret) |
| `DASHBOARD_HTTPS` | `1` | `render.yaml` ok |
| `DASHBOARD_STUB_RUNS` | unset, or `0` | — must not be `1` |
| `PYTHON_VERSION` | `3.12` (or use `.python-version`) | `render.yaml` ok |
| `DASHBOARD_USERS` | Phase 2 only | dashboard (secret) |
| `DATABASE_URL` | Phase 3 only | dashboard (secret) |

`DASHBOARD_HOST` / `DASHBOARD_PORT` aren't needed — the start command
binds `0.0.0.0:$PORT` directly (`$PORT` is set by Render).

### render.yaml template

```yaml
services:
  - type: web
    name: automation-dashboard
    runtime: python
    plan: free                        # spins down after 15 min idle, ~30–60s cold start; swap to "starter" ($7/mo) to remove it
    branch: main
    autoDeploy: true
    buildCommand: 'git config --global url."https://${GH_TOKEN}@github.com/".insteadOf "https://github.com/" && uv sync --frozen --no-dev && uv cache prune --ci'
    startCommand: "uv run --no-sync uvicorn dashboard.app:app --host 0.0.0.0 --port $PORT"
    healthCheckPath: /health
    envVars:
      - key: DASHBOARD_HTTPS
        value: "1"
      - key: PYTHON_VERSION
        value: "3.12"
      - key: SESSION_SECRET
        sync: false                   # set in the dashboard, not committed
      - key: DASHBOARD_PASSWORD_HASH
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: GH_TOKEN                  # fetches private capability repos during build
        sync: false
```

### Known gotchas

- **Cold start:** the free service spins down after 15 min idle; the
  next request waits ~30–60s while it wakes. Expected on this plan;
  `plan: starter` removes it.
- **Free usage cap:** Render free instances share 750 instance-hours /
  month per workspace — one service is well within it. A second
  always-on free service would blow the cap.
- **`uv` on Render:** Render detects `uv.lock` and provides `uv` in the
  build environment — it prefills `uv sync --frozen && uv cache prune
  --ci`; we just add `--no-dev`. `uv sync` installs the project itself,
  so `dashboard` is importable.
- **Private capability repos need `GH_TOKEN`:** `uv sync` shells out to
  `git` to fetch each capability; Render's build has no credentials, so a
  private repo fails with `could not read Username for
  'https://github.com'`. The `git config … insteadOf` prefix in the
  build command injects the PAT. Same error returns when the PAT
  expires.
- **`uv run --no-sync`** in the start command stops uv from re-syncing
  (and hitting the network) on every boot.
- **Long requests:** Render has no hard request timeout, so the 30–60s
  letter call is fine. (This is why we're not on Fly.io, which closes
  idle connections at 60s.)
- **One worker:** the default is a single uvicorn worker. The `run()`
  call is offloaded to a thread (`run_in_threadpool` in `app.py`) so it
  doesn't block the event loop — the health check keeps responding during
  a 30–60s letter. Without that, the blocked loop fails `/health`, Render
  restarts the instance mid-request, and assets 502 right after the
  result page. Scale workers or add a job queue only if real concurrency
  shows up (see `DEPLOY.md`).

---

## Log

- **2026-08-29** — First deploy to Render free
  (`automation-dashboard-r9i7.onrender.com`). Build needed `GH_TOKEN` +
  the `git config … insteadOf` prefix to fetch the private
  `cover-letter-writer` repo. First real letter run 502'd on
  `/static/*` right afterwards: the synchronous `run()` blocked the
  event loop, `/health` failed, Render restarted the instance
  mid-request. Fixed by offloading `run()` with `run_in_threadpool`
  (commit `90e4696`). Verified working.
