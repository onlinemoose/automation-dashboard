# Per-user scoping — Supabase Auth + owned rows

> **Status: DESIGN ONLY — not implemented on this branch.**
> The `feat/supabase-auth-user-scoping` branch currently carries this
> document and `migrations/2026-09-01_user_scoping.sql` and nothing else.
> The code changes described below (Stages 1–5 of the plan) were **not**
> written, because the test suite could not be run in the environment the
> overnight agent had — see the 2026-09-01 entry in `PROGRESS.md`. The
> database migration has already been applied by hand, so **the deployed
> schema is ahead of this code**: the three tables have a `user_id
> not null` column that the app does not yet write. Until the code lands,
> inserts into those tables will fail.

## The problem

The dashboard has no user identity. `dashboard/_auth.py` is a single
shared password (a scrypt hash in `DASHBOARD_PASSWORD_HASH`); a correct
password sets a signed Starlette session cookie holding exactly
`{"authed": true}`. The three app-owned tables — `background_documents`,
`job_posts`, `drafts` — are reached only through the `service_role` key
(which bypasses RLS) and carry no owner column, so every row is visible
to whoever is logged in.

The goal: real accounts via Supabase Auth, and every stored row scoped to
the user who created it, so a signed-in user sees only their own
documents, job posts, and working drafts.

## Decisions taken

- **Sign-in method** — email + password now. Magic link deferred (below).
- **Account creation** — public signup disabled; operator accounts are
  pre-created in the Supabase dashboard.
- **Existing rows** — deleted (truncated) as part of the migration. No
  backfill: an existing row has no owner and assigning one would be a
  guess.
- **Old password auth** — clean cutover. The scrypt helpers
  (`hash_password`, `verify_password`, `password_hash`) stay in
  `dashboard/_auth.py` for the offline/dev auth path only.
- **Repo structure** — all in this repo. `_auth.py` is the designated
  swap point; `user_id` scoping is the dashboard's own storage
  (CLAUDE.md rule 6). Nothing is extracted to a separate package.

## Approach — application-enforced scoping

Keep the `service_role` key. Add a `user_id uuid` column to all three
tables, thread a `user_id` argument through every store method and every
query (`.eq("user_id", uid)`), and mirror the filter in the in-memory
backends.

The store rule: `user_id: str` is the last required positional-or-keyword
parameter of every backend method and every public function, with **no
default** — so a missed call site is a loud `TypeError` at import or
collection time rather than a silent cross-user leak.

Scope **both the read and the write** in every method. The ones where a
missing filter leaks across users:

- `_documents` — `list`, `get_many`, `get`, `create` (stamp),
  `update` (filter + preserve), `delete` (filter)
- `_jobs` — `list`, `get`, `create` (stamp), `update` (filter the
  `.eq("id")` chain *and* the in-memory get-before-merge; preserve
  `user_id`), `delete` (filter)
- `_drafts` — `create_or_get` (SELECT filter **and** INSERT value **and**
  the in-memory dedupe tuple), `get`, `_save` (filter the update chain),
  `add_revision` and `undo` (scoped inner `get` *and* `_save`)

Missing the SELECT filter in `_drafts.create_or_get` is the subtle one:
user B would silently re-use user A's draft row.

### How `user_id` reaches a page

Via a second positional argument to `build_input`:

```python
def build_input(form: Mapping[str, str], user_id: str) -> Input: ...
```

This sits on a seam that already carries app-storage keys (`job_post_id`,
`background_document_ids`) — app plumbing, never a capability `Input`
field. The capability's contract never sees `user_id`. Rejected
alternatives: resolving documents and jobs in the route handler; a
`contextvar` read inside the stores.

### Session shape

The signed session cookie stays the session of record and now carries:

```python
{"user": {"id": ..., "email": ...}}
```

`is_authed` reads `request.session.get("user") is not None` instead of
`authed`.

**Existing sessions invalidate once on deploy.** An operator's current
cookie has `authed` but not `user`, so `is_authed` returns `False` and
they get one redirect to `/login`. Expected; no action needed.

## Configuration

`SUPABASE_ANON_KEY` (the publishable key) is **required** in `.env` —
`sign_in_with_password` is called with the anon key, not the service key.
When it is blank the app falls back to the offline/dev auth path, which
matches the submitted email case-insensitively against
`DASHBOARD_DEV_EMAIL` and the password against
`DASHBOARD_PASSWORD_HASH`. Both are documented in `.env.example`.

## Out of scope

- **RLS policies keyed to `auth.uid()`** — future hardening. The service
  key bypasses them anyway, so they add nothing until the app stops using
  it. Scoping is enforced in the application layer for now.
- **Magic link** — deferred, a follow-up that needs interactive
  verification (the redirect lands on a URL Supabase must be configured
  to allow). Email + password ships first.

## See also

- `migrations/2026-09-01_user_scoping.sql` — the applied schema change
  and its rollback
- `BACKGROUND_DOCUMENTS.md`, `JOB_POSTS.md`, `DRAFTS.md` — the three
  app-owned stores
