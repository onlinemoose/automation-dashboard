# Progress log

Dated entries, newest first. What's done, what's deferred, decisions
made. Read this before assuming anything about the app's current state.

## 2026-08-30 — Background documents area (Supabase)

- New app-native area, not a capability page: `/documents` CRUD for
  reusable background notes (a bio, project write-ups, company context).
  Written up in `docs/BACKGROUND_DOCUMENTS.md` (CLAUDE.md rule 6).
- `dashboard/_documents.py`: the app's own store. `supabase-py` client
  over a `background_documents` table when `SUPABASE_URL` /
  `SUPABASE_SERVICE_KEY` are set; an in-memory fallback + `warnings.warn`
  otherwise (same pattern as the ephemeral `SESSION_SECRET`), so local
  dev and the tests run with no Supabase. `uv add supabase`.
- `dashboard/app.py`: four app-native routes (`/documents`,
  `/documents/new`, `/documents/{doc_id}`, `/documents/{doc_id}/delete`),
  each `guard()`-gated. `ALLOWED_ROUTES` in `tests/test_guardrails.py`
  widened to match, with a comment that these are app-native (rule 6),
  not per-capability.
- New `"checklist"` widget in `pages/_spec.py` + `FormReader.multi()`;
  `page.html` renders it from a `documents` context var; `page_submit`
  stops flattening the form and runs `build_input` in the threadpool
  (it may hit the store).
- `cover_letter_writer.py` / `cv_writer.py`: new `background_document_ids`
  checklist field (unchecked by default). `build_input` resolves the
  ticked ids to text and prepends them to the contract's
  `background_documents`; the free-text "Background notes" box stays for
  one-off notes.
- `tests/test_documents.py` added; `uv run pytest` → 34 passed;
  `uv run lint-imports` clean.
- **Operator setup pending:** create the Supabase project + table, set
  the two env vars locally and on Render. See
  `docs/DEPLOYMENT_CHECKLIST.md`.
- Deferred: per-tool scoping (every note is offered to both writer
  pages); switching `_documents.py` to the async Supabase client if the
  blocking calls ever matter.

## 2026-08-30 — New page: `cv-writer`

- `uv add "cv-writer @ git+https://github.com/onlinemoose/cv-writer.git@v0.3.0"`
  — pin recorded in `[tool.uv.sources]`, exact commit in `uv.lock`.
  Same shape as `cover-letter-writer`: `run(Input) -> Output`, with
  `Output.cost` (`Cost`) for the footer.
- `dashboard/pages/cv_writer.py`: new `PAGE`. Fields map the contract's
  candidate inputs — `job_posting` + `cv` (required), `job_title`,
  `job_company`, `tone`, `target_length`, `region`, `emphasis` (one
  point per line), `background_documents` (one doc). `sections()`
  renders `tailored_cv` + `tailoring_note`; `run_meta()` maps
  `out.cost.*`.
- Deferred, same as the cover-letter page: `previous_draft` /
  `previous_feedback` (revision loop needs the prior output carried
  back) and the operator-config inputs `house_style` / `expert_guidance`.
- `dashboard/pages/_examples/cv_writer/`: vendored demo inputs
  (`job_posting.md`, `cv.md`, `emphasis.md`) — a neutralised posting and
  a matching fictional CV, adapted from the capability's own examples.
- Registered in `dashboard/pages/__init__.py`. Generic suite now covers
  it: `uv run pytest` → 25 passed; `uv run lint-imports` clean.

## 2026-08-30 — Bump `cover-letter-writer` to `v0.11.0`

- Bumped `cover-letter-writer` pin `v0.10.0` → `v0.11.0`
  (`[tool.uv.sources]` + `uv.lock`, `uv sync`). `v0.11.0` reworks the
  capability's internal prompt files into five layers and splits
  "style" (`house_style`) from "method" (`expert_guidance`). `Input` /
  `Output` shapes are unchanged — only the docstrings for `house_style`
  and `expert_guidance` changed, and neither field is exposed on the
  page yet. Full `pytest` green after the bump.
- `dashboard/pages/cover_letter_writer.py`: `CAPABILITY_VERSION` and the
  module docstring updated to `v0.11.0`.

## 2026-08-30 — Run cost on the result page (`run_meta`)

- Bumped `cover-letter-writer` pin `v0.9.0` → `v0.10.0` (`[tool.uv.sources]`
  + `uv.lock`). `v0.10.0` is purely additive: `Output.cost` and the
  exported `Cost` shape (`usd`, `input_tokens`, `output_tokens`,
  `cache_read_input_tokens`, `cache_write_input_tokens`). `Input`
  unchanged; full `pytest` green after the bump.
- `dashboard/pages/_spec.py`: new frozen `RunMeta` (capability,
  capability_version, cost_usd, four token counts) + optional
  `Page.run_meta: Callable[[Output], RunMeta] | None`. Second optional
  page hook alongside `sections`.
- `dashboard/pages/cover_letter_writer.py`: `CAPABILITY` /
  `CAPABILITY_VERSION` constants (kept in step with the pin), `run_meta`
  mapping `out.cost.*`, and `cost=Cost(...)` added to `EXAMPLE_OUTPUT` so
  stub mode + the generic suite render the footer offline.
- `app.py`: `page_submit` computes `meta = page.run_meta(output)` and
  passes it to `result.html`; `thousands` / `usd4` Jinja filters.
- `result.html` + `app.css`: a `.runmeta` footer under the sections —
  `$0.0123 est.`, token caption (`1,024 in · 612 out · 1,500 cache-write
  · 0 cache-read`), capability + tag. No download button. Always shown
  when the page has `run_meta` (no toggle).
- Tests: `test_pages.py` — generic, asserts the footer figures render for
  any page with `run_meta`; `test_guardrails.py` — `run_meta` returns a
  well-typed `RunMeta`.
- **Deferred (next weeks):** persisting `RunMeta` to the app's own usage
  store (SQLite first; `dashboard/_usage.py`, documented per rule 6), a
  `/usage` page (app-native, not a capability page), and — later —
  a pre-`run()` limit check (calls / spend per period) as the single
  enforcement seam. `RunMeta` is already the row shape.
- **Not touched:** downloads (the existing per-section `data:` URI already
  survives reload; no server route, no run record needed for it),
  PDF/DOCX rendering.

## 2026-08-29 — Post-deploy tidy-up

- `.python-version` = `3.12` pinned (was relying on Render's default).
- `render.yaml` added as a reference copy of the service config
  (live service was created by hand; the file doesn't bind it).
- `dashboard/__main__.py` now honours `PORT` and binds `0.0.0.0` on a
  platform, so `uv run dashboard` works as a start command too.
- Download `.md` links confirmed on the live site. Phase 1 closed.
- Left for the Render dashboard: Ignored Paths `docs/**`; optional custom
  domain.

## 2026-08-29 — First Render deploy; threadpool fix for blocking run()

- Deployed to Render free. First real run surfaced 502s on `/static/*`
  right after the result page, and an unstyled result page as a result.
- Cause: `page.run()` is synchronous (LLM call, 30–60s) and was called
  directly in the async POST handler, blocking the event loop. `/health`
  stopped responding, Render marked the instance unhealthy and restarted
  it mid-request.
- Fix: `dashboard/app.py` now offloads `run()` with
  `starlette.concurrency.run_in_threadpool`. Tests unchanged (15 pass).
- Build needed a `GH_TOKEN` env var + `git config … insteadOf` prefix in
  the build command to fetch the private `cover-letter-writer` repo.

## 2026-08-29 — Deployment target chosen: Render

- Host decision: **Render**, free web service (512 MB / 0.1 CPU; spins
  down after 15 min idle → ~30–60s cold start, accepted for now).
  Upgrade to Starter ($7/mo) later is a one-line `plan:` change. Picked
  over Railway (usage-metered) and Fly.io (60s idle-connection close is a
  hazard for our silent 30–60s letter POST).
- `docs/DEPLOYMENT_CHECKLIST.md` — living to-do: Phase 1 first deploy
  (render.yaml template, env vars, smoke test), Phase 2 multi-user auth
  (Option B, env-var hash list — not built), Phase 3 real accounts + DB
  (fastapi-users + SQLModel + Neon/Supabase — future), Phase 4 calendar
  via screenshot + vision model (future).
- Nothing deployed yet; no code changes.

## 2026-08-29 — Stub mode for cost-free UI work

- `DASHBOARD_STUB_RUNS=1` (or `create_app(stub_runs=True)`): every
  `POST /p/{slug}` renders that page's `example_output` instead of
  calling the capability. No API key, no cost, no wait. A banner shows
  while it's on. Documented in `docs/EXPERIENCE.md`, `.env.example`.
- Local `.env` is set to `1` for now (UI iteration); flip to `0` for a
  real run.
- `tests/test_pages.py`: asserts stub mode renders `example_output` and
  never calls `run()`.

## 2026-08-29 — Result sections are downloadable as .md

- `templates/result.html`: every result section now has a **Download .md**
  link beside its heading — a `data:text/markdown` URI with a `download`
  filename (`<page-slug>-<heading>.md`). No new route, no re-running the
  capability, no JavaScript; the link carries the same raw Markdown the
  page already rendered.
- Generic: applies to every page's `sections()` output, not just the
  cover letter. `tests/test_pages.py` covers it for every registered page.
- `.venv` rebuilt after the folder rename (stale absolute paths in the
  console scripts); `git remote` origin repointed to
  `github.com/onlinemoose/automation-dashboard.git`.

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
