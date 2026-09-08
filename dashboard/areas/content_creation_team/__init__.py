"""Content Creation Team — research, draft, edit and SEO-review one
finished piece of copy from a goal and a brief.

Exposes one `AREA` the shell folds in (docs/AREAS.md): the page registry
adds `page_specs` to `PAGES`, `app.py` mounts `router`.
"""

from __future__ import annotations

from dashboard.areas.content_creation_team.pages import PAGE_SPECS
from dashboard.areas.content_creation_team.routes import ROUTES, router
from dashboard.pages._spec import Area

AREA = Area(
    name="content_creation_team",
    router=router,
    nav=(("Content Creation Team", "/content"),),
    page_specs=tuple(PAGE_SPECS),
    allowed_routes=frozenset(ROUTES),
    summary=(
        "Draft, edit and SEO-review one finished piece of copy from a goal and "
        "a brief — with reviewer notes and revision history."
    ),
)
