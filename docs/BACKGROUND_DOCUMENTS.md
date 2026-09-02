# Background documents

Reusable text the writer pages can pull in — your **CV**, a bio, project
write-ups, company-context notes, answers to recurring application
questions. Kept once, picked per run, instead of pasted every time.

A document is one of two **kinds**, set by the `is_cv` flag (the "This
document is a CV" box on the document form):

- **CVs** (`is_cv = true`) — offered on the Cover Letter / CV pages in the
  "Load a saved CV" picker (`doc_picker`), and nowhere else.
- **Background notes** (`is_cv = false`, the default for a new document) —
  offered as background context in the `checklist`, and nowhere else.

`/documents` lists the two kinds under separate headings.

This is **the app's own storage** (CLAUDE.md rule 6): private to the
dashboard, no capability sees it. A page reads it only to turn a picked id
into text.

## Where it lives

| Piece | File |
|---|---|
| Store (the only module that talks to Supabase) | `dashboard/_documents.py` |
| CRUD screen | `/documents` routes in `dashboard/app.py`, `templates/documents.html`, `templates/document_form.html` |
| The pickers on a writer page | `"checklist"` (background) and `"doc_picker"` (the CV) widgets in `dashboard/pages/_spec.py` + `templates/page.html` |
| Wiring into the contract | `build_input` in `dashboard/pages/cover_letter_writer.py` and `cv_writer.py` — the picked CV id resolves to `cv`; ticked ids plus the `additional_context` textarea fold into `background_documents` |

`/documents`, `/documents/new`, `/documents/{doc_id}`,
`/documents/{doc_id}/delete` are app-native routes — not capability pages.
`tests/test_guardrails.py` lists them in `ALLOWED_ROUTES` for that reason.

## Backing store

A single Supabase (Postgres) table, reached with the `service_role` key
(the "secret" API key — `sb_secret_…` in the current key format).

When creating the project, **uncheck "Automatically expose new tables"**
(Supabase's own recommendation) so the public `anon` role gets nothing by
default. Then run, in the SQL editor:

```sql
create table background_documents (
  id         uuid primary key default gen_random_uuid(),
  title      text not null,
  body       text not null default '',
  is_cv      boolean not null default false,
  updated_at timestamptz not null default now(),
  user_id    uuid not null references auth.users(id) on delete cascade
);

create index if not exists background_documents_user_id_idx
  on background_documents (user_id);

-- The app connects only as service_role (server-side). Grant that role;
-- grant nothing to anon/authenticated, so the table is unreachable
-- without the secret key.
grant all privileges on table background_documents to service_role;

alter table background_documents enable row level security;
```

RLS is a second layer: the `service_role` key bypasses it, everything else
is denied (no policies). The browser is never handed a key.

### Configuration

| Env var | Notes |
|---|---|
| `SUPABASE_URL` | Supabase → Project Settings → API → Project URL |
| `SUPABASE_SERVICE_KEY` | the `service_role` secret. **Full access — server-side only.** Never rendered into a page, never logged, never committed. |

Both are declared in `.env.example`, `render.yaml`, and the Render
env-var table in `docs/DEPLOYMENT_CHECKLIST.md`.

### In-memory fallback

If either env var is missing, `_documents.py` uses a process-local dict
and emits a `warnings.warn` — the same shape as the ephemeral
`SESSION_SECRET` fallback in `app.py`. Nothing persists across a restart.
This keeps local dev and the test suite running with no Supabase; it is
**not** meant for production, which is why the deploy checklist says to set
the vars before the deploy lands.

## How a saved note reaches a capability

1. The writer page declares a `Field("background_document_ids", …,
   widget="checklist")`. It renders as one unchecked checkbox per saved
   background note (`is_cv = false`); CVs are not listed here.
2. On submit, `app.py` keeps the repeated values as a list (it no longer
   flattens the form) and runs `build_input` in a worker thread.
3. `build_input` calls `FormReader.multi("background_document_ids")` for
   the ticked ids and `_documents.get_documents(ids)` to fetch their text.
4. Each document body is prepended to the contract's
   `background_documents: list[str]`, ahead of anything typed into the
   free-text "Additional context" box (`additional_context`) — that box's
   whole contents are appended as one final list element, one more
   "document" for this run only. The capability renders every element the
   same way (`### Document N` under a "Supplementary background" heading);
   it can't tell a saved doc from the typed note.

Neither form field is a 1:1 mirror of the contract: `background_documents`
is fed by **two** widgets. `background_document_ids` (the checklist)
carries app-storage keys; `additional_context` (the textarea) is the
free-text half. Both are named for what they are, and `build_input` is
where they become contract data — the one deliberate exception to "a
`Field.name` matches an `Input` argument".

## Notes / limits

- **Per-user scoped.** Every query filters on `user_id`, reads and writes
  alike, and each public function takes the owning user's id as a required
  argument (`list_documents(user_id, *, is_cv=None)`,
  `get_documents(ids, user_id)`, `get_document(doc_id, user_id)`,
  `create_document(title, body, user_id, is_cv=False)`,
  `update_document(doc_id, title, body, user_id, is_cv=False)`,
  `delete_document(doc_id, user_id)`). Another user's document is invisible:
  absent from the list, `None` from `get`, a no-op to update or delete, and
  a 404 over HTTP. See `USER_SCOPING.md` and
  `migrations/2026-09-01_user_scoping.sql`.
- **CV vs background note** is the only per-tool distinction: the `is_cv`
  flag decides which writer widget offers a document (`list_documents`
  takes `is_cv=True` / `False` to filter). It was added by
  `migrations/2026-09-02_cv_flag.sql` — additive, existing rows backfilled
  to `true`. Any finer routing (a `tags` / `tools` column) can be added
  later without migrating existing rows.
- **Blocking client.** `supabase-py` is synchronous; every store call
  (including `build_input`) is wrapped in `run_in_threadpool`. Switch to
  the async client if that ever becomes a bottleneck.
- **Free-tier Supabase** pauses a project after ~7 days idle (un-pause
  from the dashboard) and does little automatic backup — export or move to
  Pro if these notes matter.
- This is the same Supabase project Phase 3 (real accounts) will reuse —
  see `docs/DEPLOYMENT_CHECKLIST.md`.
