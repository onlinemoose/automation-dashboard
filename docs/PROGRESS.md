# Progress log

Dated entries, newest first. What's done, what's deferred, decisions
made. Read this before assuming anything about the app's current state.

## 2026-08-29 — Seeded automation-dashboard; first real page

- This repo (was `cover-letter-writer-fe`, a stale capability-template
  copy) is now the automation system's dashboard, seeded from
  `experience-layer-template`. GitHub repo still needs renaming to
  `automation-dashboard`.
- Added `cover-letter-writer` as a pinned git dependency
  (`@v0.9.0`; recorded in `[tool.uv.sources]` + `uv.lock`).
- `dashboard/pages/cover_letter_writer.py` — the first real page. Exposes
  the required inputs (`job_posting`, `cv`) plus `job_title`,
  `job_company`, `tone`, `emphasis` (one point per line), background
  notes, `max_words`, `salary_expectation`, `availability`.
- **Not exposed yet:** the revision loop (`previous_draft` /
  `previous_feedback` — needs the prior output carried back) and the
  operator-config inputs (`house_style` / `expert_guidance`).
- Deleted the template's stand-in capability and example page.
- `uv run pytest` and `uv run lint-imports` pass. Running the real
  capability needs `ANTHROPIC_API_KEY` in `.env`.

## 2026-08-28 — Template created

- The experience-layer template: FastAPI + Jinja, server-rendered, no
  JavaScript. One deployable.
- **A page is a `Page`** (`dashboard/pages/_spec.py`): `fields`,
  `example_form`, `example_output`, `build_input`, `run`, `sections`.
  Two generic routes in `app.py` (`GET`/`POST /p/{slug}`) drive every
  page from its spec — adding a capability is adding a `Page`, never a
  route.
- **Auth:** single password, scrypt hash in `DASHBOARD_PASSWORD_HASH`,
  signed session cookie. No accounts, no database. `dashboard/_auth.py`
  is the one place to swap for real accounts later.
- **Guardrails:** `tests/test_guardrails.py` (no reaching past a
  capability front door into `._core` etc.; no orchestration framework;
  every page registered and well-formed) + `.importlinter` for
  `uv run lint-imports`.
- **Generic tests:** `tests/test_pages.py` covers every registered page
  — form renders each field, `example_form` submits, `build_input`
  returns the capability `Input`, `run()` is called (stubbed with
  `example_output`), `sections()` headings appear. Offline; no API key.
- **Worked example:** `dashboard/_example_capability.py` (a stand-in
  "poem writer") + `dashboard/pages/example.py`, so the template runs
  with nothing installed. Instances delete both.
- Deferred, on purpose: HTMX / progressive enhancement, a job queue for
  long calls, PDF/DOCX upload (its own future capability), Prefect
  pipeline triggers, multi-user auth.
- `uv run pytest` (13) and `uv run lint-imports` pass. Smoke-tested end
  to end against the stand-in capability.
