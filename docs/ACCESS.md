# Per-user area access control

## The problem

Auth (`docs/USER_SCOPING.md`) is binary: any signed-in operator reaches
every product area (`docs/AREAS.md`). We want to restrict *which areas* a
given user can reach — e.g. one user gets Job Application Co-Pilot but
not Content Creation Team — without a new table or a per-request
Supabase call.

## The model

- **Grants live in Supabase**, in each user's `auth.users.app_metadata`:
  ```json
  {"areas": ["job_application"]}
  ```
  Set from the Supabase dashboard (Authentication → Users → edit user →
  raw app metadata) or the Admin API / SQL, the same place accounts are
  already provisioned:
  ```sql
  update auth.users
  set raw_app_meta_data = raw_app_meta_data || '{"areas":["job_application"]}'::jsonb
  where email = 'wilko@example.com';
  ```
- **No `areas` key = every area.** Backwards compatible — an existing
  account with no key keeps full access, and so does the test suite.
- **`"areas": []` = no areas.** A way to suspend access without deleting
  the account.
- **Granularity is the area**, not the page. The stored value is a list
  of area keys: `job_application`, `content_creation_team` (matching the
  area manifest in `tests/test_guardrails.py`). Pages inherit their
  area's grant.
- **Grants are resolved once at sign-in** from `app_metadata` and carried
  in the signed session cookie alongside `id` / `email`
  (`dashboard/_auth.py`: `AuthedUser.areas`). Like those two, a change in
  Supabase takes effect on the user's **next login** — there is no
  per-request Supabase call.
- **A denied area is invisible, then 404 — never 403.** It is dropped
  from the topbar nav and the index cards; a direct URL to any of its
  routes or pages returns a plain 404. This mirrors the row-scoping
  choice in `docs/USER_SCOPING.md` (a route that fetches another user's
  row also 404s rather than 403s) — the app never confirms that a denied
  area exists.

## How it's enforced

`dashboard/_access.py` (shell module) holds a small static table — one
`AreaDecl` per area (nav links, index title/summary, page slugs, URL
prefixes) — built once from the Job Application declaration plus every
packaged `Area` (`dashboard.pages.AREAS`), and pure predicates over a
user's grant: `can_access_path`, `can_access_slug`, `visible_areas`, and
`require_slug` (a 404 helper for the generic `/p/{slug}` routes).

Three call sites:

- `guard()` in `dashboard/app.py` — the login-redirect gate every shell
  route already calls; now also 404s a denied path.
- The two generic `/p/{slug}` handlers in `dashboard/app.py` — call
  `_access.require_slug(request, slug)` right after resolving the page.
- `_guard()` in the Content Creation Team router — the area's own gate,
  mirroring the shell's.

Nav and the index no longer come from static Jinja globals; `render()` /
`_render()` inject `area_nav = _access.visible_areas(current_user)` per
request, and `base.html` / `index.html` / the holding-view templates
iterate it.

**Always-allowed paths** — `area_for_path` returns `None` for them, so
`can_access_path` allows them regardless of grant: `/`, `/login`,
`/logout`, `/health`, `/static/*`.

## Offline / dev

With `SUPABASE_ANON_KEY` unset, sign-in goes through the offline backend.
`DASHBOARD_DEV_AREAS` (comma-separated area keys) plays the same role as
`app_metadata.areas`: unset = every area, set-but-empty = none.

## Room to grow

The grant is area-level today, with room to add page-level slugs to
`AreaDecl` later without changing the storage shape (a list under
`app_metadata.areas` could as easily hold page slugs). Nothing about the
enforcement points assumes area is the finest grain forever.

## See also

- `docs/USER_SCOPING.md` — the orthogonal `user_id` row scoping (which
  *rows* a user sees, not which *areas*)
- `docs/AREAS.md` — the area boundary itself
