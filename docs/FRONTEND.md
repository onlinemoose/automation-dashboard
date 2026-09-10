# Front-end: UIKit, vendored

The shell chrome (topbar + nav sidebar) is built on [UIKit](https://getuikit.com/)
3.x — plain static files, no build step, no bundler, no MCP server. It is
consumed exactly like `dashboard/static/app.css` already was: the three
files are committed to the repo and served by the existing
`app.mount("/static", StaticFiles(...))`.

## Pinned version

**UIKit 3.25.22** — downloaded from the `uikit` npm package's published
tarball (the same release jsDelivr serves at
`https://cdn.jsdelivr.net/npm/uikit@3.25.22/dist/...`):

```
dashboard/static/uikit.min.css        # dist/css/uikit.min.css
dashboard/static/uikit.min.js         # dist/js/uikit.min.js
dashboard/static/uikit-icons.min.js   # dist/js/uikit-icons.min.js
```

These are committed, not gitignored — `pyproject.toml`'s hatchling build
already ships every non-`.py` file under `dashboard/`, so no build step
change was needed.

## Bumping the version

1. Fetch the three files for the new version, e.g. from the `uikit` npm
   package (`https://registry.npmjs.org/uikit/-/uikit-<ver>.tgz`,
   `package/dist/{css/uikit.min.css,js/uikit.min.js,js/uikit-icons.min.js}`)
   or the equivalent jsDelivr URLs above with the new version in the path.
2. Overwrite the three files in `dashboard/static/`.
3. Update the pinned version at the top of this file.
4. `uv run pytest` — `tests/test_shell.py` checks the chrome still renders;
   re-run the manual regression pass below for anything visual.

## Why UIKit

Evaluated against Tailwind + DaisyUI (needs a local CSS build and a
rebuild-before-commit discipline this repo doesn't have) and Bulma (no
build, but ships no JavaScript). UIKit ships both a plain stylesheet *and*
declarative JS components (`uk-offcanvas`, `uk-modal`, `uk-dropdown`,
`uk-tab`, …) driven entirely by `uk-*` HTML attributes — no init code, no
bundler, so it drops into a hand-written, no-build app the same way
`app.css` does.

## What changed

**Load order matters:** `uikit.min.css` loads *before* `app.css` in every
`<head>` (`base.html` and the four streamed "working…" partials) so that,
on a specificity tie, our hand-written rules win. This is deliberate and
must not be reordered — reversing it lets UIKit's un-namespaced base
styles (bare `h1`–`h6`, `p`, `table`, `blockquote`, `code`/`pre`, form
controls) leak into existing page bodies that predate UIKit.

**Chrome structure:**

- `dashboard/templates/_macros.html` — `nav_list(area_nav)` renders the
  `<ul class="uk-nav uk-nav-default">` shared by the rail and the
  off-canvas drawer.
- `dashboard/templates/_sidebar.html` — a persistent `<aside class="shell__nav uk-visible@m">`
  rail plus a `uk-offcanvas` drawer holding the same list, toggled by a
  burger button (`uk-hidden@m`) in the topbar. Included from `base.html`
  and all four streamed running partials (the two shell ones plus the two
  under `dashboard/areas/content_creation_team/templates/`, which inline
  the shell chrome rather than extending `base.html`).
- `base.html`'s topbar is now slim: brand left, a burger (mobile only) +
  the signed-in email + Sign out right. The horizontal area-link list that
  used to live in the topbar moved into the sidebar.
- A visitor with nothing to show in `area_nav` (the login / forgot-password
  / set-password pages) gets no sidebar and no burger. This is done with a
  `{% block sidebar %}{% endblock %}` override on those three templates —
  the same pattern they already use to blank `{% block nav %}`. **Not**
  simply guarding on `area_nav` being empty: an anonymous visitor's
  `area_nav` (`dashboard._access.visible_areas(None)`) is actually *every*
  area (unrestricted, not "none"), so that guard alone doesn't hide the
  sidebar pre-auth — the block override is required.
- `dashboard/_render.py`'s `asset_version()` and `dashboard/app.py`'s
  `_asset_version()` both hash the three new files into the `?v=`
  cache-bust string. Keep both in sync if you add another shared static
  asset.

**Not touched by this change:** no page body or area template was
restyled. UIKit component adoption inside page bodies (forms, buttons,
tables, modals, dropdowns) is deliberately deferred to later, page-by-page
work. `.topbar__sep`'s CSS rule in `app.css` is now dead (the markup that
used it moved into the sidebar) — left in place rather than removed as
part of this change; a later pass can drop it.

## Regression-checking a change here

There's no visual regression test — check by hand:

```
DASHBOARD_STUB_RUNS=1 uv run dashboard
```

Sign in, then click through: the index, a generic page form and result
panel, the jobs list and a job detail, documents, the draft editor, and
one Content Creation Team page. Compare against `main`. Anything that
looks like a UIKit base style leaking into content `app.css` doesn't
already cover (headings inside `.markdown` output, tables, blockquotes,
code blocks) gets a targeted override appended to `app.css` — never edit
UIKit's own files.
