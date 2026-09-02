# Job posts

Add a job posting once, analyse it into a prioritised list of what the
hiring manager is really weighing, annotate each point with where you're
strong or exposed, then load it into the Cover Letter and CV pages —
instead of pasting the posting and re-typing an emphasis list on each page.

This is **the app's own storage** (CLAUDE.md rule 6): private to the
dashboard, no capability sees it. The writer pages read it only to turn a
picked id into `job_posting` text and an `emphasis` list.

## The workflow

1. **Job posts → New job post** — paste the posting, give it a title.
2. The job's page opens in a **reading** view: the posting shown for
   reading, with **Edit** (fix a typo in the title/posting) and
   **Analyse posting**. Analysing produces two things — a prose **summary**
   of what the hiring manager is weighing, and the **emphasis** list (one
   block per requirement, a `>` line quoting the span it comes from and an
   empty `-` line for your note).
3. Once analysed, the page switches to a **working** view: the summary is
   shown read-only at the top, and below it the emphasis list renders as
   one card per requirement — an importance pill (`must-have` / `strong` /
   `nice-to-have`), the requirement sentence, the quoted span from the
   posting (all read-only), and a **note** box. **Annotate** each card —
   where you're strong, or where it's a gap — then **Save** (persists the
   emphasis *and* the summary together). **Re-analyse posting** replaces
   both (it asks first). A hand-typed / unparseable emphasis falls back to
   a plain textarea.
4. Open **Cover Letter Writer** / **CV Writer** from an analysed row's
   shortcut icon (`/p/<writer>?job_post_id=<id>`) — that is the only way
   in. The job post drives the form: it supplies `job_posting` and the
   annotated `emphasis` list from the store (the writer pages have no box
   for either; edit the emphasis on the job post itself), and its `company`
   / `job_title` pre-fill those fields. The `job_post_id` rides along in a
   hidden field — there is no dropdown — and the job's name shows as a
   plain `<h2>` below the page lede so you know which post you're writing
   against. Pick a CV document, then Run. A bare visit to `/p/<writer>`
   (no `?job_post_id=`) has no job to work from and redirects to `/jobs`.
5. The finished letter / CV is **saved on the job post**. Coming back to
   that writer for the same job (`/p/<writer>?job_post_id=<id>`, including
   the list shortcut icons) shows the saved result in place of the form.
   **Run again** on that view reopens the form with the job still picked
   (`&rerun=1`); a fresh run overwrites the stored result.

On the **Job posts** list each row has an actions cell on the right:
a delete icon always; once the post is analysed, a Cover Letter and a CV
icon appear to its left, each linking to that writer for this job
(`/p/<writer>?job_post_id=<id>`). Those links are the writer pages' only
entry point — `page_form` redirects a bare `/p/<writer>` to `/jobs`; a
foreign / unknown id resolves to no job post (nothing carried, nothing
pre-filled), and the run then fails the same way a missing id does.

## Saved writer results

Each job post carries two nullable `jsonb` slots — `cover_letter` and
`tailored_cv` — one per writer page. A completed run on
`POST /p/<writer>` (with a job post picked) is written to its slot by
`_save_result()` in `app.py`: the rendered `sections` (heading + Markdown)
plus the `RunMeta` cost fields and a `saved_at` stamp — the app's own
display copy, enough to re-render the result view, never fed back into a
capability. The page's `Page.saved_result_slot` names the column
(`"cover_letter"` / `"tailored_cv"`); `_jobs.RESULT_SLOTS` lists them.

`GET /p/<writer>?job_post_id=<id>` reads the slot and, if set, renders the
result view instead of the form (`_saved_result()` rebuilds `Section` /
`RunMeta`). `&rerun=1` on that URL — what the result view's **Run again**
button uses — bypasses this and shows the form with the job preselected.
A slot is only ever written (overwritten by the next run), never cleared
by the app; deleting the job post drops it with the row.

The slot is also written by the working-draft editor: **Save to job post**
(`POST /drafts/{id}/save`) patches one section's Markdown in the stored
payload with the edited draft, keeping the cost meta and the other
sections, then redirects here so the edit shows on the next visit. See
`docs/DRAFTS.md`.

`update_job_post(..., cover_letter=<dict>)` / `tailored_cv=<dict>` follow
the same partial-merge rule as `emphasis` / `summary`: `None` means "leave
this slot alone".

The detail screen is three states, chosen by `job.emphasis` (empty vs not)
and an `?edit=1` query flag: **reading** (Edit + Analyse), **edit**
(editable title/posting, only before the first analysis), **working**
(read-only summary + the structured emphasis cards, Re-analyse + Save). To
change the posting text *after* analysing, delete the post and add it
again.

The structured editor keeps only the **note** editable. The read-only
parts of each card ride back as hidden fields (`req_N` / `tag_N` /
`quote_N`) with `item_count`; `job_save` reassembles them + the notes into
the canonical emphasis text with `_job_analysis.emphasis_items_to_text()`
(the inverse of `parse_emphasis_items()`), so the stored value and the
writer-page parse are byte-for-byte what a plain-textarea save produced.
No JavaScript.

The summary lives only in the browser between Analyse and Save — Analyse
writes the emphasis list to the store but not the summary; the working
view carries the summary in a hidden field so **Save** writes both. Leave
the page after Analyse without saving and the summary is gone (the
emphasis list is not).

## Where it lives

| Piece | File |
|---|---|
| Store (the only module that talks to Supabase) | `dashboard/_jobs.py` |
| Analysis step + emphasis format/parse | `dashboard/_job_analysis.py` |
| Screens | `/jobs*` routes in `dashboard/app.py`, `templates/jobs.html`, `templates/job_form.html`, `templates/job_detail.html` |
| The job on a writer page | hidden `job_post_id` field (`"hidden"` widget) carried from `?job_post_id=`; bare-visit redirect in `page_form` |
| Wiring into the contract | `build_input` in `dashboard/pages/cover_letter_writer.py` and `cv_writer.py` |

`/jobs`, `/jobs/new`, `/jobs/{job_id}`, `/jobs/{job_id}/analyse`,
`/jobs/{job_id}/delete` are app-native routes — not capability pages.
`tests/test_guardrails.py` lists them in `ALLOWED_ROUTES` for that reason,
the same category as `/documents`.

## The analysis is a capability

Reading a posting and ranking its requirements is LLM domain logic, so it
lives in its own capability module — **`job-analyst`** (imported as
`job_analyst`) — consumed here like `cover-letter-writer`. It is **not** an
orchestration flow: the chain is two capabilities with a human annotation
step in the middle, so the composition lives in the experience layer (this
app), at an allowed seam.

`dashboard/_job_analysis.analyse()` calls `job_analyst.run(Input(posting=…))`
and maps the `Output` onto this app's `Analysis`:

```python
# dashboard/_job_analysis.py
import job_analyst

def analyse(posting: str) -> Analysis:
    return _to_analysis(job_analyst.run(job_analyst.Input(posting=posting)))
```

Needs `ANTHROPIC_API_KEY` in the environment (CLAUDE.md rule 7). Anthropic
SDK errors (auth, rate limit) propagate to the request.

**What `job-analyst` actually returns**, and how it's mapped:

```python
Input(posting: str, role_hint: str | None = None, count: int = 12,
      expert_guidance: str | None = None)

Requirement(point: str, quote: str, importance: str, rationale: str)
    # importance: "critical" | "high" | "medium" | "low"

Output(requirements, summary, company: str, job_title: str,
       reading_between_the_lines: list[str], cost)
```

- **importance** `critical → must-have`, `high`/`medium → strong`,
  `low → nice-to-have` (`_IMPORTANCE` in `_job_analysis.py`).
- **`reading_between_the_lines`** is appended to `Analysis.summary` as a
  `**Reading between the lines**` bullet list (the summary is rendered
  through the Markdown filter on the job detail page).
- **`company`** / **`job_title`** (job-analyst ≥ v0.2.0) — the hiring
  company and role title as written in the posting, `""` when the posting
  omits them. `job_analyse` persists them to the `job_posts.company` /
  `job_posts.job_title` columns on every analyse (refreshed like the
  emphasis list). They pre-fill the writer forms — see *Prefilling the
  writer forms* below.
- **`quote`** is already verified verbatim against the posting by the
  capability; the dashboard passes it straight through to `Emphasis.quote`.
- **`cost`** maps field-for-field onto the `RunMeta` footer.

### Release pin

`pyproject.toml` pins `job-analyst` to a git tag in `[tool.uv.sources]`:
`job-analyst = { git = "https://github.com/onlinemoose/job-analyst.git", rev = "vX.Y.Z" }`.
Upgrading = bump the `rev`, `uv lock`, add a `docs/PROGRESS.md` entry. For
local dev against an unreleased change, point it at a sibling checkout
(`{ path = "../job-analyst", editable = true }`) and switch back to the tag
before committing.

## Prefilling the writer forms

The **Cover Letter Writer** / **CV Writer** pages have plain, editable
`job_title` and `job_company` text inputs. The page is always opened with
`?job_post_id=<id>` in the URL (the shortcut icons on the Job posts list —
the only entry point); `page_form` reads the job post and pre-fills those
inputs from `job_post.job_title` / `job_post.company` — declared per field
with `Field(..., from_job_post="job_title")` / `from_job_post="company"`
(app-storage plumbing, like `job_post_id` itself, not a contract argument).

- The values are a **starting point, not a lock**: the user edits or
  clears them in the form, and `build_input` reads the submitted field —
  the job post is never a submit-time fallback, so a cleared field reaches
  the capability as `None`.
- **Server-side, no JavaScript.** The pre-fill happens on the `GET` that
  renders the form. There is no dropdown to re-pick a job (the
  `job_post_id` is a hidden field), so nothing can desync.
- A foreign / unknown id resolves to no job post → nothing pre-filled;
  the bare `/p/<writer>` (no id) redirects to `/jobs`.

## The emphasis format

One block per requirement, blank line between blocks:

```
Show you can own pricing and P&L conversations with executives
> comfortable owning pricing and P&L discussions with C-level stakeholders
- Led the 2022 pricing rework but never presented directly to C-level — partial gap

Take ML features from prototype to production
> experience shipping ML-powered features end to end
- Strong: retrieval assistant went prototype→prod with adoption numbers
```

- a plain line → the requirement (the instruction to the writer)
- a `>` line → the exact span of the posting it is anchored to → `Emphasis.quote`
- a `-` line → your own note

A plain line may also lead with an importance tag — `[must-have]`,
`[strong]`, `[nice-to-have]` — which `requirements_to_emphasis_text()`
writes and the parsers strip back off.

`parse_annotated_emphasis()` turns each block into one `Emphasis` for the
writer pages. **v1 folds the note into `Emphasis.point`** as
`"…\n\nCandidate note: …"` — the `cover-letter-writer` / `cv-writer`
contract has no dedicated `candidate_note` field yet (a later follow-up).
A block with no `>`/`-` markers is read as one requirement per plain line,
so a hand-typed "one point per line" list still works unchanged.

`parse_emphasis_items()` / `emphasis_items_to_text()` are the other pair:
they split the same text into `EmphasisItem` rows (importance, requirement,
quote, note — all separate) for the structured editor and join them back,
losslessly for the canonical format above.

## `job_post_id` is not a contract argument

Like `background_document_ids`, the `Field("job_post_id", …,
widget="hidden")` carries an app-storage key, not a capability `Input`
argument. `build_input` is where it becomes contract data (`job_posting`
text + a parsed `emphasis` list). It's the second deliberate exception to
"a `Field.name` matches an `Input` argument".

## Backing store

A single Supabase (Postgres) table, reached with the `service_role` key —
same project and pattern as Background documents (`docs/BACKGROUND_DOCUMENTS.md`).
In the SQL editor:

```sql
create table job_posts (
  id           uuid primary key default gen_random_uuid(),
  title        text not null,
  posting      text not null,
  emphasis     text not null default '',
  summary      text not null default '',
  company      text not null default '',
  job_title    text not null default '',
  cover_letter jsonb,
  tailored_cv  jsonb,
  updated_at   timestamptz not null default now(),
  user_id      uuid not null references auth.users(id) on delete cascade
);

create index if not exists job_posts_user_id_idx on job_posts (user_id);

grant all privileges on table job_posts to service_role;
alter table job_posts enable row level security;
```

**Migrations for an existing deployment** — run once each in the SQL editor:

```sql
-- the summary column was added after the table shipped
alter table job_posts add column if not exists summary text not null default '';

-- the saved writer-result slots (Cover Letter / CV re-shown per job post)
alter table job_posts add column if not exists cover_letter jsonb;
alter table job_posts add column if not exists tailored_cv  jsonb;

-- company / job title, extracted by analyse (job-analyst >= v0.2.0),
-- used to pre-fill the writer forms
alter table job_posts add column if not exists company   text not null default '';
alter table job_posts add column if not exists job_title text not null default '';
```

Adding a `text` column with a constant default, or a nullable `jsonb`
column with no default, is metadata-only on Postgres — instant, no table
rewrite, no meaningful lock. Each inherits the table's existing RLS and
grants.

Uses `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` (already declared for
Background documents). If either is missing, `_jobs.py` uses a process-local
dict and emits a `warnings.warn` — nothing persists across a restart. Fine
for local dev and tests; set the vars for anything real.

## Notes / limits

- **Analyse overwrites the emphasis box.** It's step 2 of the workflow —
  analyse, then annotate, then Save. Re-analysing (only offered once the
  list has content) asks for confirmation first.
- **The summary is persisted by Save, not by Analyse.** Analyse writes the
  emphasis list to the store immediately but keeps the summary in a hidden
  form field; **Save** writes emphasis and summary together. A `summary`
  column on `job_posts` holds it (see the migration under *Backing
  store*). It is read-only in the UI.
- **`company` / `job_title` are persisted by Analyse** (unlike the
  summary), refreshed on every analyse, `""` when the posting omits them.
  They have no field on the Job Post screens — correction happens in the
  writer form they pre-fill. See *Prefilling the writer forms*.
- **The posting is only editable before the first analysis.** After that
  the detail screen shows it read-only; changing it means deleting the
  post and re-adding it.
- **No async.** Analysis and the store calls are synchronous and wrapped in
  `run_in_threadpool`, like the writer `run()` and the Background documents
  store.
- **Per-user scoped.** Every query filters on `user_id`, reads and writes
  alike, and each public function takes the owning user's id as its last
  required argument (`list_job_posts(user_id)`,
  `get_job_post(job_id, user_id)`, `create_job_post(title, posting, user_id)`,
  `update_job_post(job_id, user_id, *, title=…, posting=…, emphasis=…,
  summary=…, company=…, job_title=…, cover_letter=…, tailored_cv=…)`,
  `delete_job_post(job_id, user_id)`). Another user's post is invisible:
  absent from the list and the picker, `None` from `get`, a no-op to update
  or delete, and a 404 over HTTP. See `USER_SCOPING.md` and
  `migrations/2026-09-01_user_scoping.sql`.
- **No per-job scoping of the picker.** Every job post you own is offered on
  both writer pages.
