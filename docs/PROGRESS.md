# Progress log

Dated entries, newest first. What's done, what's deferred, decisions
made. Read this before assuming anything about the app's current state.

## 2026-08-31 — Job analyse: guard the empty-result case

A German CPO posting analysed to nothing: the `job-analyst` model reply
came back with the whole analysis nested one level down
(`{"analysis": {…}}`), a shape the capability's `_normalise_payload`
didn't recover, so `run()` returned an empty `Output`. The analyse route
then overwrote the emphasis list with a blank and rendered an empty page.

- **Fix in the capability** (`../job-analyst`, not this repo — it's
  domain logic): `_normalise_payload` now also unwraps a plain dict
  nested under a wrapper key, alongside the JSON-string shapes it already
  handled. Not language-specific; the German analysis itself was fine.
  Still a local path override here — not yet tagged/pushed.
- **Guard here** — `POST /jobs/{id}/analyse`: when `analysis.requirements`
  is empty, the route no longer touches the stored emphasis. It returns
  `502` and re-renders the detail page with a `notice` ("came back empty
  — nothing was changed. Try again."). New `notice` slot in
  `job_detail.html`; covered by `test_analyse_empty_result_keeps_the_emphasis_and_warns`.

## 2026-08-31 — Targeted revision: edit one span of a result draft

Branch `targeted-revision`. A capability result section can now be opened
as an **editable draft**: select a span, give an instruction, and the new
`targeted-editor` capability revises *that span only* — proposed as a
diff, spliced in on accept, linear undo. Written up in `docs/DRAFTS.md`.

- **New capability — `targeted-editor`** (`targeted_editor`), consumed
  like `job-analyst`. Contract: `document` + `selection` + `instruction`
  (+ optional `kind`) → `revised` (the span replacement only) + `note` +
  `cost`. `pyproject.toml` pins it plus a `[tool.uv.sources]` **path**
  override (`{ path = "../targeted-editor", editable = true }`) — the
  repo is tagged `v0.1.0` locally but not yet pushed. Switch to a
  `git … @v0.1.0` pin once it's on GitHub, then `uv lock` + an entry here.
- **`dashboard/_drafts.py`** — the app's own store (Supabase table
  `drafts` + in-memory fallback, same pattern as `_jobs.py`). One draft
  per `(slug, section, source_hash)` via `create_or_get_draft`.
  `apply_revision()` is the one piece of real text logic (a splice);
  **undo is replay** — drop the last revision, recompute `current` from
  `original` + what remains. `original` is never mutated.
- **`dashboard/_targeted_edit.py`** — the capability adapter (thin,
  modelled on `_job_analysis.py`): `revise()` calls
  `targeted_editor.run(...)` and maps `Output` → this app's `Revision`.
  `kind_for_section()` maps an Output-section slug to the capability's
  `kind` steer. Needs `ANTHROPIC_API_KEY`.
- **`dashboard/app.py`** — six app-native routes: `POST /drafts`
  (open/create), `GET /drafts/{id}` (editor), `POST /drafts/{id}/revise`
  (propose — **does not mutate**), `.../accept` (splice + record),
  `.../undo`, `GET .../download`. Listed in `ALLOWED_ROUTES` as
  app-native, the same category as `/jobs`. `/revise` honours
  `DASHBOARD_STUB_RUNS` (canned proposal, no API key).
- **`templates/draft.html` + `static/draft-edit.js` + `app.css`** — raw
  Markdown in a `<pre white-space:pre-wrap>`; selection offsets map 1:1
  to `current`. Floating "Revise…" → instruction → diff (word-level) +
  note + `RunMeta` footer → accept / retry / reject. New selections are
  locked out while a proposal is open (one edit at a time). "Undo last",
  "Download .md", a history list.
- **`templates/result.html`** — each result section gets an "Edit draft"
  button (`POST /drafts` with that section's text). The stateless run
  path is otherwise unchanged.
- **`tests/test_drafts.py`** — splice + replay units, `create_or_get`
  dedupe, `/revise` doesn't mutate, `/accept` records + re-splices,
  `/undo` reverts, `/download` returns `current`. `targeted_editor.run`
  stubbed autouse. `uv run pytest` (68) and `uv run lint-imports` clean.
  Also verified end to end in a real browser against Supabase + the live
  capability (select → revise → diff → accept → undo → download).

## 2026-08-30 — Wire the real `job-analyst` capability into the analyse step

The `/jobs/{id}/analyse` step now calls the real capability instead of the
fixed placeholder list.

- **`job-analyst` is a dependency.** `pyproject.toml` adds `job-analyst`
  plus a `[tool.uv.sources]` **path** override
  (`{ path = "../job-analyst", editable = true }`) — it isn't tagged yet.
  Switch to a `git … @vX.Y.Z` pin once it releases.
- **`dashboard/_job_analysis.py`** — `analyse()` calls
  `job_analyst.run(Input(posting=…))` and `_to_analysis()` maps `Output`:
  importance `critical→must-have`, `high`/`medium→strong`,
  `low→nice-to-have`; `reading_between_the_lines` appended to the summary
  as a Markdown bullet list; `Cost` mapped field-for-field. The
  format/parse helpers are unchanged. Needs `ANTHROPIC_API_KEY` in the
  env (put it in `.env`).
- **`dashboard/app.py`** — the analyse route's `RunMeta` now reports
  `capability="job-analyst"` and the installed version
  (`_job_analysis.capability_version()`) instead of `"(stub)"`.
- **`tests/test_jobs.py`** — new autouse `stub_analyst` fixture
  monkeypatches `job_analyst.run` so the suite stays offline, the same
  way `test_pages.py` stubs a page's `run`.
- `uv run pytest` and `uv run lint-imports` clean.
- **Note:** the analyse route does not honour `DASHBOARD_STUB_RUNS` — it
  always calls the capability. Fine for now; revisit if a no-key
  click-through of `/jobs` is wanted.

## 2026-08-30 — Job posts area + analyse → annotate → writer workflow

Branch `job-post-analysis`. Experiment: add a posting once, analyse it into
a prioritised emphasis list, annotate each point, then load it into the
Cover Letter and CV pages. Written up in `docs/JOB_POSTS.md`.

- **New app-native area, not a capability page:** `/jobs` CRUD +
  `/jobs/{id}/analyse`. `ALLOWED_ROUTES` in `tests/test_guardrails.py`
  widened (same category as `/documents`). `dashboard/_jobs.py` — the
  app's own store, `job_posts` Supabase table with the in-memory fallback
  pattern; `templates/jobs.html`, `job_form.html`, `job_detail.html`;
  `base.html` nav link.
- **The analysis is a capability, not orchestration.** Reading a posting
  and ranking its requirements is LLM domain logic → its own repo,
  `job-post-analyst`, pinned like `cover-letter-writer`. Not a Prefect
  flow: two capabilities with a human annotation step between them, so the
  composition stays in the experience layer at an allowed seam. **That
  repo isn't built yet** — `dashboard/_job_analysis.analyse()` returns a
  fixed placeholder list; `docs/JOB_POSTS.md` has the contract to build
  against and the swap-in point.
- **Emphasis format** carries the analysis + the user's notes as text: a
  plain line = the requirement, a `> ` line = the quoted span from the
  posting (→ `Emphasis.quote`), a `- ` line = the candidate's note.
  `parse_annotated_emphasis()` in `_job_analysis.py`. **v1 folds the note
  into `Emphasis.point`** (`"…\n\nCandidate note: …"`) — no
  `cover-letter-writer` contract change. A marker-free block is still one
  point per line, so hand-typed lists are unaffected.
- **New `"picker"` widget** (single-select `<select>` of saved job posts),
  fed a `jobs` context var like `checklist` gets `documents`. On
  `cover_letter_writer.py` / `cv_writer.py`: a `job_post_id` field (a
  second `Field.name` that isn't a contract arg, like
  `background_document_ids`). `build_input` loads `job_posting` +
  `emphasis` from the store when it's set, else the two textareas as
  before; `job_posting` is no longer HTML-`required` (enforced in
  `build_input` unless a job post is picked).
- `tests/test_jobs.py` added; `uv run pytest` → 50 passed;
  `uv run lint-imports` clean.
- **Operator setup pending:** `create table job_posts …` in the existing
  Supabase project (DDL in `docs/JOB_POSTS.md`).
- **Follow-ups:** build + pin `job-post-analyst` and replace the
  placeholder; wire its real `Cost` into the analyse-page cost footer;
  later, a `candidate_note` field on `Emphasis` to stop folding the note
  into `point`; a nicer per-point annotation UI than one textarea.

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
