# Progress log

Dated entries, newest first. What's done, what's deferred, decisions
made. Read this before assuming anything about the app's current state.

## 2026-09-02 — Result view: trim the secondary section's chrome

Branch `new-user-flow`. On the Cover Letter / CV result view the header
crumb link (`← Cover Letter Writer`) is gone — it led to a bare,
unrelated-looking form, and **Run again** already covers going back. The
working / error holding views keep their crumb.

`Section` gains `editable: bool = True`. Both writers mark their
`"What it targeted"` note `editable=False`, and `_result_panel.html`
gates the **Edit draft** button on `section.editable | default(true)` —
the note is read / download only, but an undefined value (a stale
`Section` before a server restart, an old saved row) still shows the
button rather than silently dropping it; only an explicit `False` hides
it. `_result_payload` / `_saved_result` carry the flag so a re-shown
saved result matches. Tests in `test_jobs.py` assert the note has a
Download link but no `action="/drafts"` form, exactly one **Edit draft**
button on the result view, and no `class="crumb"`.

## 2026-09-02 — Writer results persist per job post

Branch `new-user-flow`. A finished **Cover Letter Writer** / **CV Writer**
run is now saved on the job post it was written for, and re-opening that
writer for the same job shows the saved result instead of a blank form.

- `job_posts` gets two nullable `jsonb` columns, `cover_letter` and
  `tailored_cv` (one per writer). `_jobs.py`: `JobPost` gains the two
  fields, `RESULT_SLOTS`, an `_as_result()` jsonb coalescer, and
  `update_job_post(..., cover_letter=…, tailored_cv=…)` following the same
  `None` = "leave alone" partial-merge as `emphasis` / `summary`.
- `Page` gains `saved_result_slot: str | None` — the column name. Set to
  `"cover_letter"` / `"tailored_cv"` on the two writer pages; unset
  elsewhere. Not a route branch on `slug`, so the guardrail holds.
- `app.py`: `_result_payload()` stores the rendered `sections` + the
  `RunMeta` fields + a `saved_at` stamp; `_saved_result()` rebuilds
  `Section` / `RunMeta` from it. `POST /p/<slug>` reads `job_post_id` from
  the form (an app-storage key, like `background_document_ids` — never a
  capability `Input` field) and, after a successful `run()`, writes the
  payload to the slot — in the streamed slow path too, best-effort so a
  store failure never sinks the response. `GET /p/<slug>?job_post_id=<id>`
  renders the result view from the slot when it's set.
- `_result_panel.html`: **Run again** carries `?job_post_id=<id>&rerun=1`
  when a `job_post_id` is in context; `rerun` skips the saved-result view
  and opens the form with the job kept. No visible UI change otherwise.
- Stub mode saves nothing (no real `run()`); a run with no job post
  picked saves nothing.
- **Supabase migration** (run once): `alter table job_posts add column if
  not exists cover_letter jsonb;` and `… tailored_cv jsonb;`. Nullable
  `jsonb`, no default — metadata-only, inherits the table's RLS/grants.
  Full DDL in `docs/JOB_POSTS.md`.
- Tests in `tests/test_jobs.py`: slot round-trip + scoping; the saved
  view shows for its job and not the form (asserts no `<textarea>` /
  `action="/p/…"`); `?rerun=1` forces the form with the job kept; a
  finished run lands in the right slot only; no-job-post run saves
  nothing. `tests/test_pages.py` unchanged (its posts carry no
  `job_post_id`).

## 2026-09-02 — Manual edits on the draft editor

Branch `new-user-flow`. The "Editing draft" page (`/drafts/{id}`, shared
by Cover Letter and CV) only allowed AI span revisions even though the UI
implied hand-editing. First cut added a separate **Edit text** toggle
(read-only `<pre>` swaps for a textarea) — reworked after feedback that a
second edit mode inside what's already a form view was poor UX. The
`<pre>` is directly editable instead: no button, no mode switch.

- `POST /drafts/{id}/edit` → `_drafts.record_manual_edit(...)`, which
  appends one whole-span `Revision` (`instruction = "(manual edit)"`).
  No `_drafts` backend or schema change — it rides the existing
  `apply_revision` / `replay` / undo path, so `original` stays immutable,
  the edit shows in History, and `Undo last` reverts it. No-op when the
  text is unchanged. (Unchanged from the first cut.)
- `templates/draft.html`: `#draft-doc` is now `contenteditable="true"`.
  `draft-edit.js` intercepts Enter and paste so it stays plain text (a
  browser's native contenteditable handling of Enter reaches for a
  `<div>`/`<br>`, which `textContent` doesn't render as `"\n"` — it would
  desync the span-selection offsets), tracks a dirty flag, and autosaves
  on blur — flushed first if Download or Undo is used before that fires.
  A span proposal still briefly sets `contentEditable = "false"` while
  open ("one edit in flight").
- Deliberately *not* a `<textarea>`: that would need rewriting the
  Range-based span-selection/offset code the AI-revise flow already
  relies on, and textareas have no equivalent to `Range.getBoundingClientRect()`
  for placing the floating **Revise…** button at a selection. contenteditable
  reuses that code untouched.
- `test_guardrails.py` ALLOWED_ROUTES gets `/drafts/{draft_id}/edit`.

## 2026-09-01 — CV comes from a saved document, not a paste

Branch `new-user-flow`. Both writers lose the `cv` textarea; the CV is now
picked from the Documents library.

- New `doc_picker` widget (a `<select>` of the user's documents, single
  select) rendered by `templates/page.html`; `_wants_documents` now true
  for it as well as `checklist`.
- Both writer pages get a `cv_document_id` field (app-storage key, like
  `job_post_id`). `build_input` resolves it to the document body as `cv`;
  no pick → `FormError({"cv_document_id": "Load a saved CV."})`. Raw `cv`
  in `EXAMPLE_FORM` stays as the fallback that keeps the generic page
  test runnable. Both pages now have no HTML-`required` field, so
  `test_empty_submission_is_rejected_when_fields_are_required` skips for
  them — the per-page 422 tests in `test_documents.py` cover it.
- Documents list: `Delete` button → trash icon (`.iconbtn iconbtn--danger`
  in a `.pagelist__actions` cell), matching the Job posts list. Lede
  reworded to include the CV.
- No file upload — documents stay pasted text / Markdown (decided with
  the user).
- Dropped the "Points to emphasise" (`emphasis`) field from both writers
  too. A run must come from a picked job post, whose Emphasis list always
  overrode that field anyway — it was dead in the UI. `build_input` still
  reads a raw `emphasis` value as the example/API fallback; `job_post_id`
  help text reworded.

## 2026-09-01 — Trim the generic capability page chrome

Branch `new-user-flow`. `templates/page.html` (drives every `/p/<slug>`
page — currently Cover Letter Writer and CV Writer): dropped the
"← All capabilities" crumb (the top nav covers navigation) and the
"Load example inputs" link. `example_form` and the `?example=1` prefill
route are untouched — the suite still relies on them, they're just no
longer surfaced in the UI.

## 2026-09-01 — Writer pages drop the free-text Job posting box

Branch `new-user-flow`. Both **Cover Letter Writer** and **CV Writer**
lose the `job_posting` textarea field. The "Load a saved job post" picker
is now the only way to supply the posting.

- `build_input`: when no job post resolves it raises
  `FormError({"job_post_id": "Load a saved job post."})` instead of
  reading a `job_posting` field. A raw `job_posting` value is still
  honoured when present, so "Load example" and direct API posts keep
  working (`EXAMPLE_FORM` still carries the example posting).
- Picker help text reworded; `FormError` now imported in both pages.
- Tests: neither writer form renders `name="job_posting"`; a run with no
  job post picked is a 422 on the picker.

## 2026-09-01 — Job posts list: icon actions + writer shortcuts

Branch `new-user-flow`.

- Each row on `/jobs` now has an actions cell on the right (rows are
  top-aligned with the title). The delete button is an icon (still a
  POST form + confirm). Once a post is analysed, a Cover Letter icon and
  a CV icon appear to the left of delete, each `title`/`aria-label`ed
  with the feature name.
- The writer icons link to `/p/cover-letter-writer?job_post_id=<id>` /
  `/p/cv-writer?job_post_id=<id>`. `page_form` now honours a
  `job_post_id` query param — it preselects the picker field, so the
  posting + emphasis load exactly as picking the job by hand. A foreign
  or unknown id preselects nothing (`build_input` already ignores an
  unresolvable id).
- Icons are inline SVG (first icons in the app); new `.iconbtn` /
  `.pagelist__actions` CSS.

## 2026-09-01 — Structured emphasis editor on the analysed job view

Branch `new-user-flow`. The single emphasis textarea on the working view
is replaced by one card per requirement: an importance pill (`must-have`
/ `strong` / `nice-to-have`), the requirement sentence, the quoted span
(all read-only), and an editable **note** box.

- New in `_job_analysis.py`: `EmphasisItem`, `parse_emphasis_items()`,
  `emphasis_items_to_text()` — the round-trip between the annotated
  `emphasis` text and structured rows, lossless for the canonical format.
- **No JavaScript.** Each card's read-only fields ride back as hidden
  inputs (`req_N` / `tag_N` / `quote_N`) with `item_count`; `job_save`
  detects those and reassembles the canonical text. The plain `emphasis`
  field still drives the edit-state form and any non-structured post, and
  a hand-typed / unparseable emphasis falls back to the textarea.
- Storage format, the writer-page parse, summary persistence and
  Re-analyse are all unchanged.
- `test_analysed_post_shows_the_emphasis_editor_not_the_posting` became
  `test_analysed_post_shows_the_structured_emphasis_editor`; added
  parse/serialise round-trip tests and a structured-save HTTP test.

## 2026-09-01 — Job analysis summary is now saved with the emphasis

Branch `new-user-flow`. The analysis summary used to be shown once on the
Analyse response and then lost. It now persists:

- New `summary` column on `job_posts` (`text not null default ''`) plus a
  `JobPost.summary` field, `_jobs.py` backend + `update_job_post` support.
  **Live Supabase needs a one-line migration** —
  `alter table job_posts add column if not exists summary text not null
  default '';` (in `docs/JOB_POSTS.md`).
- The working view shows the summary read-only at the top and carries it
  in a hidden `<textarea name="summary">`. `POST /jobs/{id}` (`job_save`)
  reads it and writes emphasis + summary in one update.
- **Analyse still does not persist the summary** — only `Save` does (as
  the user specified). Leaving the page after Analyse without saving
  loses the summary; the emphasis list is written immediately as before.
- Cost/token footer stays transient (only on the Analyse response).
- Tests: store round-trips `summary` on partial update; the Analyse
  response shows + carries the summary; `Save` persists both and the
  summary comes back on the next GET.

## 2026-09-01 — Job post detail screen split into read / edit / work states

Branch `new-user-flow`. `/jobs/{job_id}` no longer opens as a wall of
editable textareas. It is now three states, chosen by `job.emphasis`
(empty vs not) and an `?edit=1` query flag:

- **Reading** (saved, never analysed) — the posting is shown read-only
  with an **Edit** link and an **Analyse posting** button, grouped in a
  bottom-right `.form-actions` row.
- **Edit** (`?edit=1`, still unanalysed; also the target of a save
  validation error) — editable title + posting, **Cancel** / **Save**.
- **Working** (analysed) — posting read-only, only the emphasis list
  editable; **Re-analyse posting** (confirm) + **Save**. The save form
  carries `title`/`posting` as hidden inputs so `job_save` is unchanged;
  Re-analyse is a second submit button using `formaction`.

New CSS: `.form-actions` (right-aligned button row, modelled on
`.draft__actions`) and `.posting-readonly`. `job_detail` /`job_save`
pass an `edit` flag to the template; no route changes. To edit a
posting after analysis you must delete and re-add the post — noted in
`docs/JOB_POSTS.md`.

## 2026-09-01 — Homepage reframed around the Job Application Co-Pilot

Branch `new-user-flow`. First cut at a task-first entry point instead of a
flat list of capability pages.

- The homepage "Capabilities" list no longer iterates the `PAGES`
  registry. It leads with a single **Job Application Co-Pilot** entry that
  links to `/jobs` (the job posts area — add a posting, analyse it, then
  build an application from it).
- The Cover Letter and CV Writer pages are unchanged and still served at
  their `/p/{slug}` routes; they are just no longer linked from the
  homepage. Where to surface them inside the flow is still open.
- Dropped the "One page per capability. Pick one to run it." lede.
- Renamed the "Background documents" area to **Documents** across the UI
  (nav, the list and form screens, and the checklist field labels on the
  writer pages). The store, routes (`/documents`) and code names are
  unchanged.
- `test_index_lists_every_page` became `test_index_shows_the_copilot_entry`.

## 2026-09-01 — Supabase Auth deployed + two-account isolation verified

The branch below merged to `main` (`56bdcc0`) and auto-deployed to Render.

- `SUPABASE_ANON_KEY` set as a Render service env var (it was already in
  the local `.env`). Without it on the host the app silently uses the
  offline login, so it is now a **required** env var everywhere the app
  runs.
- The migration had been applied by hand the night before; the three
  tables started empty.
- Forced sign-out confirmed on the live site — the pre-accounts cookie
  redirected once to `/login`; signing in with the operator's Supabase
  email + password worked.
- Two-account isolation checked by hand on the live site: a second
  Supabase user saw none of the operator's documents, job posts or
  drafts; `/documents/<id>`, `/jobs/<id>`, `/drafts/<id>` for a foreign
  row returned 404; a document created by the second user stayed
  invisible to the operator.

Still deferred: magic-link sign-in; RLS policies keyed to `auth.uid()`
(see the entry below and `docs/USER_SCOPING.md`).

## 2026-09-01 — Supabase Auth + per-user data isolation

Branch `feat/supabase-auth-user-scoping`. Real accounts via Supabase
Auth, and every row in the app's three own stores scoped to the user who
created it. 98 tests pass, `lint-imports` clean.

**What shipped**

- **Auth** (`dashboard/_auth.py`) — email + password against Supabase
  Auth using the *anon* key. `AuthedUser(id, email)`, a backend protocol
  with a Supabase and an offline implementation, `sign_in`,
  `current_user`, `current_user_id`. The signed session cookie now holds
  `{"user": {"id", "email"}}` and `is_authed` reads it. The scrypt
  helpers stay, used only by the offline/dev login.
- **Scoping** (`_documents.py`, `_jobs.py`, `_drafts.py`) — `user_id` is
  the last required argument of every backend method and public
  function, no default, so a missed call site is a `TypeError` at
  collection time. Both the read and the write are filtered in each
  method; the in-memory backends mirror the Supabase behaviour exactly.
- **The page seam** — `build_input(form, user_id)`. App plumbing on the
  seam that already carries `job_post_id` and `background_document_ids`;
  the capability `Input` never sees it. No route added or removed.

**Deploy steps (all done 2026-09-01 — see the entry above)**

1. **Run `docs/migrations/2026-09-01_user_scoping.sql`** in the Supabase
   SQL editor if you have not already. It truncates the three tables,
   adds `user_id`, swaps the `drafts` unique constraint for the
   per-user one, and indexes `user_id`. It carries its own rollback,
   which cannot restore truncated rows.
2. **Add `SUPABASE_ANON_KEY` to `.env`** — required. Without it the app
   silently falls back to the offline login. `DASHBOARD_DEV_EMAIL` is
   optional and dev-only. Both are documented in `.env.example`.
3. **Existing sessions invalidate once.** A cookie from before accounts
   has `authed` but no `user`, so it reads as signed out — one redirect
   to `/login`. Expected, no action.
4. **Verify two-account isolation by hand** — sign in as each of two
   Supabase accounts and confirm neither sees the other's documents, job
   posts or drafts. The Supabase code paths were written by analogy to
   the existing `_SupabaseBackend` methods and are the one part the test
   suite cannot reach.

**Deferred**

- **Magic link** — not implemented. Email + password ships first; the
  magic-link flow needs interactive verification of the redirect URL.
  See `docs/USER_SCOPING.md`.
- **RLS policies keyed to `auth.uid()`** — future hardening, out of
  scope. The `service_role` key bypasses them, so they add nothing until
  the app stops using it. Scoping is enforced in the application layer.

**Notes**

- Every scoping test was checked by mutation: the filter removed, the
  test confirmed red, the filter restored. Worth keeping up — a scoping
  test that cannot fail is worse than none.
- Jinja escapes `'` to `&#39;`, so `assert "A's note" not in resp.text`
  passes whether or not scoping works. Caught one such false pass;
  fixtures now avoid apostrophes.
- This work was first attempted by an unattended overnight run, which
  stopped at Stage 0: two of the four pinned capability repos
  (`cover-letter-writer`, `targeted-editor`) are private and the cloud
  session had no GitHub grant for them, so `uv sync` failed and neither
  `pytest` nor `lint-imports` could run. Resolved by installing the
  Claude GitHub App for the `onlinemoose` account.

## 2026-08-31 — Live word count on the slow pages (cv-writer v0.5.0, cover-letter-writer v0.13.0)

Both capabilities gained an optional keyword-only `on_progress` callback
(`Progress(characters, words, seconds)`, ~2×/sec while the reply
streams). Wired into the dashboard:

- `Page.progress: bool` — set on `cv_writer` and `cover_letter_writer`
  alongside `slow=True`.
- `_streamed_result` now bridges the worker thread to the response
  stream (`loop.call_soon_threadsafe` + an `asyncio.Queue`) and emits a
  `<script>window.__progress(<words>)</script>` chunk per update,
  coalescing any backlog. Non-progress slow pages keep the bare
  keepalive.
- `_running_open.html` shows an elapsed clock and, once words arrive,
  `Writing… N words · M:SS`. `window.__stopProgress` is called from the
  close/error templates.

Verified under real uvicorn: holding view at ~1s, `__progress` chunks as
the callback fires, result swapped in at completion. Pins → v0.5.0 /
v0.13.0, `uv.lock` + `CAPABILITY_VERSION` + docstrings updated. Generic
test suite covers the progress path per page. 72 tests pass,
`lint-imports` clean.

## 2026-08-31 — Bump cv-writer v0.4.0, cover-letter-writer v0.12.0

Both capabilities now stream their model call internally
(`messages.stream().get_final_message()`), cap output at `max_tokens=8_000`
(was 16_000), set an explicit client `timeout=300s` + `max_retries=1`, and
raise on a `max_tokens` stop instead of returning a truncated document.
`run()`'s signature is unchanged — no page changes beyond the pins and
`CAPABILITY_VERSION`. Paired with the streamed "slow page" response below,
this is the fix for the CV Writer deploy-only timeout on long roles.

`pyproject.toml` pins + `uv.lock` updated; `CAPABILITY_VERSION` and the
page docstrings follow. 70 tests pass, `lint-imports` clean.

## 2026-08-31 — Slow pages: stream the result to beat the proxy timeout

CV Writer (and Cover Letter Writer) timed out **only on the deployed
server**, worst for a German role. Cause: `cv_writer.run()` is one
non-streaming LLM call at `max_tokens=16_000`; a full Lebenslauf runs for
minutes, and Render's proxy drops any request that produces no response
bytes for ~100s. Local has no such proxy, so it always came back there.

Fix in this repo (experience-layer concern, not the capability):

- `Page` gains `slow: bool = False`. `cover_letter_writer` and `cv_writer`
  set `slow=True`; the draft-revision and job-analyse routes are quick and
  untouched.
- `POST /p/{slug}` for a slow page now returns a `StreamingResponse`:
  flush a holding view at once, a keepalive comment every 15s while
  `run()` works in the threadpool, then the result panel + a swap script
  (`_running_close.html`) — or an in-body error (`_running_error.html`),
  since the `200` is already committed.
- `result.html` split: the panel moved to `_result_panel.html`, shared by
  the plain result page and the streamed close.
- Holding-view spinner CSS in `app.css`; `X-Accel-Buffering: no` +
  `Cache-Control: no-cache` on the stream.

Verified under real uvicorn: first byte at ~1s, keepalives at 15s/30s, a
35s run completes and swaps in cleanly. 70 tests pass, `lint-imports`
clean. Not a job queue — that's still a deliberate later addition.

## 2026-08-31 — Pin job-analyst and targeted-editor to git tags

Both capabilities were local `[tool.uv.sources]` path overrides while
their repos caught up. Now on GitHub:

- `targeted-editor` — new private repo `onlinemoose/targeted-editor`,
  pushed with tag `v0.1.0`.
- `job-analyst` — the `recover-nested-tool-payload` fix (empty-result
  bug above) is merged to its `main` and tagged `v0.1.0`.

`pyproject.toml` now pins both with `{ git = "…", rev = "v0.1.0" }`
alongside `cover-letter-writer` and `cv-writer`; `uv lock` records the
commits. No path overrides left. 70 tests pass, `lint-imports` clean.

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
