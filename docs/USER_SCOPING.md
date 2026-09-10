# Per-user scoping — Supabase Auth + owned rows

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
- **Account creation** — invite-only. An admin invites from the Supabase
  dashboard; the invited user sets their own password at
  `/auth/set-password` (see "Setting a password" below), so the admin
  never handles it. Public signup stays disabled.
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

### The shipped signatures

```python
# dashboard/_documents.py
list_documents(user_id)
get_documents(ids, user_id)
get_document(doc_id, user_id)
create_document(title, body, user_id)
update_document(doc_id, title, body, user_id)
delete_document(doc_id, user_id)

# dashboard/_jobs.py
list_job_posts(user_id)
get_job_post(job_id, user_id)
create_job_post(title, posting, user_id)
update_job_post(job_id, user_id, *, title=None, posting=None, emphasis=None)
delete_job_post(job_id, user_id)

# dashboard/_drafts.py
create_or_get_draft(slug, section, text, user_id)
get_draft(draft_id, user_id)
record_revision(draft_id, user_id, *, instruction, selection, span_start,
                span_len, revised, note="", cost=None)
undo_last(draft_id, user_id)

# dashboard/_auth.py
sign_in(email, password) -> AuthedUser | None
current_user(request)    -> AuthedUser | None   # AuthedUser(id, email)
current_user_id(request) -> str | None
```

`update_job_post` and `record_revision` take `user_id` *before* the `*`,
so the keyword-only arguments after it are unchanged.

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

Each of these is covered by a test that was checked by mutation — the
filter was removed, the test confirmed red, the filter restored. A
route that fetches and 404s on `None` therefore returns **404, not 403**
for another user's row; the routes don't distinguish "doesn't exist"
from "not yours", and deliberately don't try.

One trap worth recording: Jinja escapes `'` to `&#39;`, so an assertion
that `"A's note" not in response.text` passes whether or not scoping
works. Test fixtures use apostrophe-free titles.

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

## Setting a password — invite & recovery

`sign_in_with_password` assumes the user already has a password. Two
paths create or replace one, both server-side, no client JavaScript:

- **Invite** — an admin clicks *Invite* in the Supabase dashboard
  (Authentication → Users). The user gets an email; its link lands on
  `GET /auth/set-password?token_hash=…&type=invite`.
- **Forgot password** — the login page links to `GET /auth/forgot`, which
  posts an email to `POST /auth/forgot` → `reset_password_for_email`. The
  recovery email's link lands on the same page with `type=recovery`. The
  response is always the same ("if that address has an account…") — it
  never reveals whether the address is registered.

`GET /auth/set-password` renders one password field with `token_hash` and
`type` in hidden fields — no Supabase call yet. `POST /auth/set-password`
(`dashboard/_auth.py:set_password`) builds a **fresh** Supabase client,
calls `verify_otp({token_hash, type})` then `update_user({password})`, and
on success writes the same `session["user"]` dict that `login_submit`
does — the user lands signed in at `/`. A `PasswordSetError` (expired or
already-used link, or a password the project policy rejects) re-renders
the form with the message.

`token_hash` is single-use and short-lived, so it rides in the hidden
field between GET and POST with no server-side state. Offline
(`SUPABASE_ANON_KEY` unset) these routes render an "isn't configured"
notice instead of the form — the dev login has no tokens.

### Required Supabase console config

The default Supabase email links point at Supabase's own `/auth/v1/verify`
endpoint, which redirects back with the tokens in the URL *fragment* — a
server-rendered app never sees that. Point the templates at this app:

1. **Authentication → Email Templates → Invite user** — link →
   `{{ .SiteURL }}/auth/set-password?token_hash={{ .TokenHash }}&type=invite`
2. **Authentication → Email Templates → Reset Password** — link →
   `{{ .SiteURL }}/auth/set-password?token_hash={{ .TokenHash }}&type=recovery`
3. **Authentication → URL Configuration → Site URL** — the deploy origin
   (e.g. `https://…onrender.com`); `http://127.0.0.1:8000` locally.
4. Keep email signups disabled — invites are unaffected.
5. Supabase's built-in email is rate-limited (~2–4/hour) and not for
   production — configure a custom SMTP provider before real use.

Area grants (`docs/ACCESS.md`) are still set separately on the invited
user's `app_metadata`; the invite doesn't carry them.

## Out of scope

- **RLS policies keyed to `auth.uid()`** — future hardening. The service
  key bypasses them anyway, so they add nothing until the app stops using
  it. Scoping is enforced in the application layer for now.
- **Magic link login** — passwordless *sign-in* is still deferred. The
  invite / recovery *password-set* flow above is implemented and uses the
  same kind of email link, verified server-side.

## Area access

This document covers *which rows* a signed-in user sees. Orthogonal to
that: `docs/ACCESS.md` covers *which product areas* a user can reach at
all — a per-user grant on `AuthedUser.areas`, resolved at sign-in from
`app_metadata` and enforced with a 404 on a denied area, same as this
scoping enforces a 404 on another user's row.

## See also

- `migrations/2026-09-01_user_scoping.sql` — the applied schema change
  and its rollback
- `BACKGROUND_DOCUMENTS.md`, `JOB_POSTS.md`, `DRAFTS.md` — the three
  app-owned stores
- `ACCESS.md` — per-user area access control
