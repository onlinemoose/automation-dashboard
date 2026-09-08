"""The page registry — one entry per capability the dashboard exposes,
plus the product areas folded in.

To add a page:
  1. `uv add "<capability> @ git+https://.../<capability>.git@vX.Y.Z"`
  2. Create `dashboard/pages/<capability>.py` exporting `PAGE`
     (copy an existing page).
  3. Import it here and add its `PAGE` to `PAGES`.
docs/EXPERIENCE.md has the full walk-through; docs/AREAS.md covers adding
a whole area (its `page_specs` are folded in below).
"""

from __future__ import annotations

from itertools import chain

from dashboard.pages import cover_letter_writer, cv_writer
from dashboard.pages._spec import Page
from dashboard.areas.content_creation_team import AREA as CONTENT_CREATION_TEAM

# Product areas — self-contained slices mounted by the composition roots
# (this file folds in their pages; `dashboard/app.py` mounts their routers).
AREAS = (CONTENT_CREATION_TEAM,)

PAGES: list[Page] = [
    cover_letter_writer.PAGE,
    cv_writer.PAGE,
    *chain.from_iterable(a.page_specs for a in AREAS),
]

PAGES_BY_SLUG: dict[str, Page] = {page.slug: page for page in PAGES}
