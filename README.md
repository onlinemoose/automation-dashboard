# automation-dashboard

**The automation system's dashboard — the experience layer.** One small
web app that puts a usable face on the capability modules: one page per
capability, where the form fields *are* that capability's inputs and the
results view *is* its output. The app collects the form, calls the
capability's `run()`, and renders what comes back. It holds no domain
logic of its own.

Live (private — an account per operator): https://automation-dashboard-r9i7.onrender.com

The rules this app must not break are in **`CLAUDE.md`** (Claude Code
reads it automatically). The prose version and the "add a page"
walk-through are in **`docs/EXPERIENCE.md`**. Full system architecture:
`automation-architecture/ARCHITECTURE.md`.

---

## What's in it

**Capability pages** (`dashboard/pages/`, one per capability, all driven
by the generic `GET`/`POST /p/{slug}` routes):

| Page | Capability |
|---|---|
| Cover Letter Writer | `cover-letter-writer` |
| CV Writer | `cv-writer` |

**The app's own areas** — its own storage, not a capability's
(`CLAUDE.md` rule 6):

- **Background documents** (`/documents`) — reusable notes you tick into a
  writer page. `docs/BACKGROUND_DOCUMENTS.md`.
- **Job posts** (`/jobs`) — stored postings, with an *analyse* step that
  calls the `job-analyst` capability for emphasis points.
  `docs/JOB_POSTS.md`.
- **Working drafts** (`/drafts/{id}`) — span-level revision of a result,
  backed by the `targeted-editor` capability; undo by replay.
  `docs/DRAFTS.md`.

**Accounts** — sign-in is email + password against **Supabase Auth**, and
every stored row is scoped to the signed-in user. Public signup is off;
operator accounts are created in the Supabase dashboard. How it works and
the one-time migration: `docs/USER_SCOPING.md`,
`docs/migrations/2026-09-01_user_scoping.sql`.

---

## Run it locally

```
uv sync
cp .env.example .env        # then fill it in — the comments in that file explain each key
uv run dashboard           # http://127.0.0.1:8000
```

Key env (all in `.env`, which is gitignored):

- `SESSION_SECRET` — a stable random string; signs the session cookie.
- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` — the app's data store. Unset →
  in-memory backends that don't survive a restart (fine for a quick look).
- `SUPABASE_ANON_KEY` — enables real Supabase Auth. Blank → an offline
  dev login: `DASHBOARD_DEV_EMAIL` + the scrypt hash in
  `DASHBOARD_PASSWORD_HASH` (generate one with
  `uv run python -m dashboard.hashpw`).
- `DASHBOARD_STUB_RUNS=1` — every page returns its canned example output,
  no capability call, no API cost.

Checks:

```
uv run pytest             # every page renders + runs end to end; the guardrails hold
uv run lint-imports       # no orchestration framework crept in
```

---

## Deploy

One `uvicorn` service on **Render**, auto-deploying from `main`. The
host-agnostic serving notes are in `docs/DEPLOY.md`; the Render-specific
plan, the env-var list and the `render.yaml` reference are in
`docs/DEPLOYMENT_CHECKLIST.md`. `docs/PROGRESS.md` is the dated log —
read it before assuming anything about the current state.

---

## How it fits the system

- Depends on capabilities as **pinned git dependencies**
  (`<name> @ git+https://…@vX.Y.Z`), recorded in `uv.lock`. Calls their
  `run()` directly. Nothing depends on this app.
- May **trigger** a Prefect pipeline via its API, but never defines flows
  or tasks.
- Deploys as **one deployable**; capabilities ride along as installed
  dependencies.
