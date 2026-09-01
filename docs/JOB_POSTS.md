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
2. On the job's page, **Analyse posting** — fills the emphasis box with the
   requirements the posting implies, each on its own block with a `>` line
   quoting the span of the posting it comes from and an empty `-` line for
   your note. Re-analysing replaces the list.
3. **Annotate** — after each `>` line, write your own comment on a line
   starting `-`: where the point resonates with your experience, or where
   it's a gap. **Save.**
4. On **Cover Letter Writer** / **CV Writer**, pick the job in **Load a
   saved job post**. It fills `job_posting` and `emphasis` from the store
   and overrides the two boxes below. Run.

## Where it lives

| Piece | File |
|---|---|
| Store (the only module that talks to Supabase) | `dashboard/_jobs.py` |
| Analysis step + emphasis format/parse | `dashboard/_job_analysis.py` |
| Screens | `/jobs*` routes in `dashboard/app.py`, `templates/jobs.html`, `templates/job_form.html`, `templates/job_detail.html` |
| The picker on a writer page | `"picker"` widget in `dashboard/pages/_spec.py` + `templates/page.html` |
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

Output(requirements, summary, reading_between_the_lines: list[str], cost)
```

- **importance** `critical → must-have`, `high`/`medium → strong`,
  `low → nice-to-have` (`_IMPORTANCE` in `_job_analysis.py`).
- **`reading_between_the_lines`** is appended to `Analysis.summary` as a
  `**Reading between the lines**` bullet list (the summary is rendered
  through the Markdown filter on the job detail page).
- **`quote`** is already verified verbatim against the posting by the
  capability; the dashboard passes it straight through to `Emphasis.quote`.
- **`cost`** maps field-for-field onto the `RunMeta` footer.

### Local dev / release pin

`job-analyst` isn't tagged yet, so `pyproject.toml` overrides it to a path:
`job-analyst = { path = "../job-analyst", editable = true }` (a sibling
checkout). Once it cuts a release, swap that for
`{ git = "https://github.com/onlinemoose/job-analyst.git", rev = "vX.Y.Z" }`,
`uv lock`, and add a `docs/PROGRESS.md` entry.

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

`parse_annotated_emphasis()` turns each block into one `Emphasis`. **v1
folds the note into `Emphasis.point`** as `"…\n\nCandidate note: …"` — the
`cover-letter-writer` / `cv-writer` contract has no dedicated
`candidate_note` field yet (a later follow-up). A block with no `>`/`-`
markers is read as one requirement per plain line, so a hand-typed
"one point per line" list still works unchanged.

## `job_post_id` is not a contract argument

Like `background_document_ids`, the `Field("job_post_id", …,
widget="picker")` carries an app-storage key, not a capability `Input`
argument. `build_input` is where it becomes contract data (`job_posting`
text + a parsed `emphasis` list). It's the second deliberate exception to
"a `Field.name` matches an `Input` argument".

## Backing store

A single Supabase (Postgres) table, reached with the `service_role` key —
same project and pattern as Background documents (`docs/BACKGROUND_DOCUMENTS.md`).
In the SQL editor:

```sql
create table job_posts (
  id         uuid primary key default gen_random_uuid(),
  title      text not null,
  posting    text not null,
  emphasis   text not null default '',
  updated_at timestamptz not null default now(),
  user_id    uuid not null references auth.users(id) on delete cascade
);

create index if not exists job_posts_user_id_idx on job_posts (user_id);

grant all privileges on table job_posts to service_role;
alter table job_posts enable row level security;
```

Uses `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` (already declared for
Background documents). If either is missing, `_jobs.py` uses a process-local
dict and emits a `warnings.warn` — nothing persists across a restart. Fine
for local dev and tests; set the vars for anything real.

## Notes / limits

- **Analyse overwrites the emphasis box.** It's step 2 of the workflow —
  analyse, then annotate, then Save. The page asks for confirmation before
  re-analysing a list that already has content.
- **No async.** Analysis and the store calls are synchronous and wrapped in
  `run_in_threadpool`, like the writer `run()` and the Background documents
  store.
- **Per-user scoped.** Every query filters on `user_id`, reads and writes
  alike, and each public function takes the owning user's id as its last
  required argument (`list_job_posts(user_id)`,
  `get_job_post(job_id, user_id)`, `create_job_post(title, posting, user_id)`,
  `update_job_post(job_id, user_id, *, title=…, posting=…, emphasis=…)`,
  `delete_job_post(job_id, user_id)`). Another user's post is invisible:
  absent from the list and the picker, `None` from `get`, a no-op to update
  or delete, and a 404 over HTTP. See `USER_SCOPING.md` and
  `migrations/2026-09-01_user_scoping.sql`.
- **No per-job scoping of the picker.** Every job post you own is offered on
  both writer pages.
