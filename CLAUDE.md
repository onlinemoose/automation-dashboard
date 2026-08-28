# CLAUDE.md — Experience Layer (the dashboard)

This repo is **the automation system's dashboard** — the experience
layer. One small web app that puts a usable face on the capability
modules. One page per capability — the page's form fields *are* that
capability's inputs, its results view *is* that capability's output. The
app collects the form, calls the capability's `run()`, and renders what
comes back. It holds no domain logic of its own.

It was made from `experience-layer-template`; that repo holds the pattern
and the rules below, which travel with this `CLAUDE.md`.

> **Part of a larger system.** Read `automation-architecture/ARCHITECTURE.md`
> (sibling repo) first — it defines the three layers (capabilities →
> orchestration → experience) and which rules are system-wide. This repo
> is the *experience* layer described there.

## Mental model

The dashboard is **the reception desk**. It hands each visitor the
job-order form the right contractor (capability) needs, passes the
filled form through, and shows what comes back. It knows *which*
contractors exist and *what each one's form looks like* — nothing about
how the work is done. The moment real logic starts living here, a
capability is missing.

## The layers — and where this repo sits

- **Capability modules** — one job each, plain-Python libraries with a
  `run(Input) -> Output` front door. Consumed here as pinned git
  dependencies.
- **Orchestration** — a separate Prefect project that chains capabilities
  into pipelines. This app may *trigger* one via the Prefect API; it
  never defines flows or tasks.
- **Experience** ← *this repo*. The web app. Depends on capabilities.
  Nothing depends on it.

## Rules — do not break these

1. **Thin.** Collect inputs → call one capability's `run()` (or trigger a
   pipeline) → render the result. No domain logic. Anything that encodes
   *how the work is done* belongs in a capability.
2. **Front door only.** Import a capability's public names
   (`run`, `Input`, `Output`, and any exported shapes) — never
   `<capability>._core`, `._contract`, or a `_private` name.
   `tests/test_guardrails.py` enforces this.
3. **Dependencies point downward and are pinned.** Each capability is a
   pinned git dependency (`<name> @ git+https://…@vX.Y.Z`) recorded in
   `uv.lock`. No capability depends on this app. Local dev may override a
   pin to a path with `[tool.uv.sources]`.
4. **A page mirrors a contract.** One `Page` per capability. Its `fields`
   are that capability's `Input`; its `sections()` render its `Output`.
   When a contract changes, its page here is the single place that
   changes. A page never invents inputs the contract doesn't have.
5. **Compose only at allowed seams.** To chain capabilities (e.g. text
   extraction → cover letter): call each `run()` in sequence in a page
   handler, or trigger a Prefect flow. Never make one capability call
   another.
6. **Storage is the app's own and declared.** Saved drafts, run history,
   accounts — private to this app, written up in `docs/`, never into a
   capability's space (capabilities have none).
7. **Config and secrets at the edge.** API keys (`ANTHROPIC_API_KEY`,
   etc.) live in this app's environment; capabilities read them from the
   environment they already expect. Nothing hard-coded, nothing
   committed. `.env` is gitignored; `.env.example` is tracked.
8. **One deployable.** This app is a single service with its own
   lifecycle. Upgrading a capability = bump the pin + `uv lock` + a
   `docs/PROGRESS.md` entry, on this app's schedule.
9. **Prefect client only.** May import the Prefect API *client* to
   trigger a flow; never `@flow` / `@task` / a scheduler.
   `uv run lint-imports` forbids `prefect` outright until that exception
   is deliberately made.

## Structure

```
dashboard/
  app.py               FastAPI app: login, an index, and two generic routes
                       (GET/POST /p/{slug}) that drive every page from its Page spec
  _auth.py             single-password session login (scrypt hash in the env)
  _render.py           capability Markdown output -> HTML
  hashpw.py            `python -m dashboard.hashpw` -> a password hash for .env
  pages/
    _spec.py           Page, Field, Section, FormReader, FormError — the page contract
    __init__.py        PAGES registry
    cover_letter_writer.py   page for the cover-letter-writer capability
  templates/           base, login, index, page (generic form), result
  static/app.css       plain, restyle to taste
docs/
  EXPERIENCE.md        the rules in prose + "Adding a page" walk-through
  DEPLOY.md            serving it (uvicorn + reverse proxy, env, TLS)
  PROGRESS.md          dated log, newest first
tests/
  test_pages.py        generic: every registered page renders + runs end to end (run() stubbed)
  test_auth.py         the login gate
  test_guardrails.py   the rules above, as assertions
.importlinter          `uv run lint-imports`: no orchestration framework
```

Managed with `uv` (`uv run ...`, `uv add ...`).

## Running it

```
uv run dashboard                       # http://127.0.0.1:8000
uv run python -m dashboard.hashpw      # make a DASHBOARD_PASSWORD_HASH
```

## Checking the guardrails

```
uv run pytest              # pages render + run end to end; the rules hold
uv run lint-imports        # no orchestration framework crept in
```

## Adding a capability page

The recurring task. Full version in `docs/EXPERIENCE.md`; in short:

1. `uv add "<capability> @ git+https://github.com/onlinemoose/<capability>.git@vX.Y.Z"`
2. Copy an existing page (`dashboard/pages/cover_letter_writer.py`) to `dashboard/pages/<capability>.py`.
   Point it at the real `run` / `Input`; write `fields`, `example_form`,
   `example_output`, `build_input`, `sections`.
3. Register its `PAGE` in `dashboard/pages/__init__.py`.
4. `uv run pytest` — the generic suite now covers it.
5. `docs/PROGRESS.md` entry.

## Deploying — see docs/DEPLOY.md

This app is its own deployable: `uvicorn` behind a reverse proxy, with
`SESSION_SECRET`, `DASHBOARD_PASSWORD_HASH`, and any capability API keys
in the environment. Capabilities ride along as installed dependencies;
they are never deployed on their own.
