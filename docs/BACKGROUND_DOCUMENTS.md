# Background documents

Reusable written context the writer pages can pull in — a bio, project
write-ups, company-context notes, answers to recurring application
questions. Kept once, picked per run, instead of pasted every time.

This is **the app's own storage** (CLAUDE.md rule 6): private to the
dashboard, no capability sees it. A page reads it only to turn a picked id
into text.

## Where it lives

| Piece | File |
|---|---|
| Store (the only module that talks to Supabase) | `dashboard/_documents.py` |
| CRUD screen | `/documents` routes in `dashboard/app.py`, `templates/documents.html`, `templates/document_form.html` |
| The picker on a writer page | `"checklist"` widget in `dashboard/pages/_spec.py` + `templates/page.html` |
| Wiring into the contract | `build_input` in `dashboard/pages/cover_letter_writer.py` and `cv_writer.py` |

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
  updated_at timestamptz not null default now()
);

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
   document.
2. On submit, `app.py` keeps the repeated values as a list (it no longer
   flattens the form) and runs `build_input` in a worker thread.
3. `build_input` calls `FormReader.multi("background_document_ids")` for
   the ticked ids and `_documents.get_documents(ids)` to fetch their text.
4. Each document body is prepended to the contract's
   `background_documents: list[str]`, ahead of anything typed into the
   free-text "Background notes" box (which is kept, for one-off notes).

The field name is `background_document_ids`, not the contract argument —
it carries app-storage keys, and `build_input` is where they become
contract data. It's the one deliberate exception to "a `Field.name`
matches an `Input` argument".

## Notes / limits

- **No per-tool scoping.** Every saved document is offered to both writer
  pages. A `tags` / `tools` column can be added later without migrating
  existing rows.
- **Blocking client.** `supabase-py` is synchronous; every store call
  (including `build_input`) is wrapped in `run_in_threadpool`. Switch to
  the async client if that ever becomes a bottleneck.
- **Free-tier Supabase** pauses a project after ~7 days idle (un-pause
  from the dashboard) and does little automatic backup — export or move to
  Pro if these notes matter.
- This is the same Supabase project Phase 3 (real accounts) will reuse —
  see `docs/DEPLOYMENT_CHECKLIST.md`.
