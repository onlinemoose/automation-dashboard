# Areas — self-contained slices that share only the shell

The dashboard is one deployable, but it is not one product. It hosts
**product areas**: a job-application co-pilot today, event research next.
An area is a vertical slice — its own pages, app-owned stores, capability
adapters, routes, templates, and docs. The only thing two areas share is
the **shell**: auth, the generic `/p/{slug}` page contract, streaming,
Markdown render, `base.html`, the page registry.

**Why name the boundary.** A person — or an LLM — only ever works one area
at a time. Without the boundary written down, a task scoped to Event
Research can read and edit every Job Application file, and vice versa; the
two grow tendrils into each other and the "one small app you can hold in
your head" is gone. Naming the areas keeps each one's blast radius to
itself, and `tests/test_guardrails.py` makes "areas never import each
other" a failing test rather than a code-review note.

## The map

| Bucket | Owns |
|---|---|
| **Shell** | `dashboard/app.py` (routing skeleton, `/p/{slug}`, streaming, `create_app`), `dashboard/_auth.py`, `dashboard/_render.py`, `dashboard/pages/_spec.py`, `dashboard/pages/__init__.py`, `dashboard/hashpw.py`, `templates/{base,login,index,page,result,_result_panel,_running_*}.html`, `static/app.css`, `docs/{EXPERIENCE,DEPLOY,DEPLOYMENT_CHECKLIST,USER_SCOPING,AREAS}.md`, `tests/test_{pages,auth,auth_backend,guardrails}.py`. |
| **Job Application Co-Pilot** (entry `/jobs`) | `dashboard/pages/{cover_letter_writer,cv_writer}.py` (+ `dashboard/pages/_examples/`), `dashboard/_{documents,jobs,drafts,job_analysis,targeted_edit}.py`, the `/documents* /jobs* /drafts*` route blocks in `app.py`, `templates/{jobs,job_form,job_detail,documents,document_form,draft}.html`, `static/draft-edit.js`, `docs/{JOB_POSTS,DRAFTS,BACKGROUND_DOCUMENTS}.md`, `tests/test_{jobs,drafts,documents}.py`. Capabilities: cover-letter-writer, cv-writer, job-analyst, targeted-editor. |

The single source of truth for the module- and route-level boundary is the
**area manifest** in `tests/test_guardrails.py` (`SHELL_MODULES`,
`SHELL_ROUTES`, `AREAS`). It lives in the test module so it never ships in
the runtime.

### Guardrail

`tests/test_guardrails.py` enforces three things:

- `test_every_dashboard_module_is_claimed_by_the_manifest` — every `.py`
  under `dashboard/` is shell or belongs to exactly one area.
- `test_areas_do_not_cross_import` — an area's files import only their own
  area, the shell, and capability front doors. Shell files import no area,
  except the **composition roots** `dashboard.app` and `dashboard.pages`,
  which mount the areas (routes and page specs).
- `test_every_route_belongs_to_shell_or_one_area` — `ALLOWED_ROUTES` is
  the shell's routes plus each area's, kept disjoint; a new route in
  `app.py` must be claimed by exactly one area.

## Job Application stays flat for now

Job Application is the incumbent. Its files sit directly under
`dashboard/` rather than `dashboard/areas/job_application/`. That is
deliberate: it is already isolated by the guardrail, and moving ~15 files
+ their imports + templates buys nothing today. It may move under
`areas/` later, on its own schedule.

**Designated first slice of that move:** the `/documents*`, `/jobs*` and
`/drafts*` route blocks in `app.py` plus their module-top helpers
(`_resolve_span`, `_result_payload`, `_saved_result`, `_save_result`,
`_wants_documents`, `_job_post_driven`) lift into
`dashboard/areas/job_application/routes.py` as an `APIRouter`. Do this
**when Event Research lands**, not before — Event Research is the second
consumer that shows whether the shared `render` / `guard` / templates
shell surface is shaped right. Doing it speculatively would design that
surface against a single caller. See the route-extraction analysis in
`~/.claude/plans/rippling-stirring-engelbart.md` for the full reasoning.

The orthogonal, do-anytime cleanup: a `require_user` + `load_draft`
`Depends` pass over `app.py` (removes the repeated `guard(request)` /
`current_user_id(request)` / fetch-or-404 preamble, ~80–100 lines). It
needs no area move and shrinks whatever the extraction later carries.

## Adding an area (the Event Research recipe)

Adding an area **never edits an existing area's files**. Concretely:

### 1. The folder

```
dashboard/areas/event_research/
  __init__.py        exposes `AREA` (see below)
  routes.py          an `APIRouter` — every route this area declares
  pages/             per-capability Page specs, + _examples/
  _<store>.py        app-owned stores (same shape as _documents.py)
  _<adapter>.py      one capability adapter per seam
  templates/         area-only templates
  static/            area-only JS/CSS (base app.css stays shell)
  docs/              one .md per sub-feature
  CLAUDE.md          the nested instruction (template below)
```

### 2. `__init__.py` — one export the shell consumes

```python
from dataclasses import dataclass
from fastapi import APIRouter

from dashboard.areas.event_research.routes import router
from dashboard.areas.event_research.pages import PAGE_SPECS

@dataclass(frozen=True)
class Area:
    name: str
    router: APIRouter
    nav: tuple[tuple[str, str], ...]   # (label, href) for the index
    page_specs: tuple                  # Page objects to fold into PAGES
    allowed_routes: frozenset[str]     # mirrors the manifest entry

AREA = Area(
    name="event_research",
    router=router,
    nav=(("Event Research", "/events"),),
    page_specs=tuple(PAGE_SPECS),
    allowed_routes=frozenset({"/events", "/events/new", "/events/{event_id}", ...}),
)
```

### 3. Mount it in the shell (the only shell edits)

`dashboard/pages/__init__.py`:

```python
from itertools import chain
from dashboard.areas.event_research import AREA as EVENT_RESEARCH

AREAS = [EVENT_RESEARCH]
PAGES: list[Page] = [
    cover_letter_writer.PAGE, cv_writer.PAGE,
    *chain.from_iterable(a.page_specs for a in AREAS),
]
```

`dashboard/app.py` (once, near the other `app.mount` / router lines):

```python
from dashboard.pages import AREAS
for area in AREAS:
    app.include_router(area.router)
```

### 4. The manifest entry

In `tests/test_guardrails.py`, add to `AREAS`:

```python
"event_research": {
    "modules": {"dashboard.areas.event_research"},   # package prefix — covers the whole folder
    "routes": {"/events", "/events/new", "/events/{event_id}", ...},
},
```

`test_every_dashboard_module_is_claimed_by_the_manifest` fails until the
prefix is listed; `test_areas_do_not_cross_import` fails the moment an
`event_research` file imports a `dashboard._jobs` / `dashboard.pages.cv_writer`
/ etc.

### 5. The nested `CLAUDE.md`

Drop this in `dashboard/areas/event_research/CLAUDE.md` (Claude Code
auto-loads the nearest one):

```markdown
You are in the **Event Research** area. Edit only files under this folder
and the shell listed in `docs/AREAS.md`. Do not open
`dashboard/areas/*` for any other area, and do not open the Job
Application files (`dashboard/_{documents,jobs,drafts,job_analysis,targeted_edit}.py`,
`dashboard/pages/{cover_letter_writer,cv_writer}.py`, their templates or
docs). A change that seems to need cross-area edits means the boundary is
wrong or the thing belongs in the shell — stop and ask.
```

### 6. Log it

A `docs/PROGRESS.md` entry, newest first.
