"""The page registry — one entry per capability the dashboard exposes.

To add a page:
  1. `uv add "<capability> @ git+https://.../<capability>.git@vX.Y.Z"`
  2. Create `dashboard/pages/<capability>.py` exporting `PAGE`
     (copy an existing page).
  3. Import it here and add its `PAGE` to `PAGES`.
docs/EXPERIENCE.md has the full walk-through.
"""

from __future__ import annotations

from dashboard.pages import cover_letter_writer
from dashboard.pages._spec import Page

PAGES: list[Page] = [
    cover_letter_writer.PAGE,
]

PAGES_BY_SLUG: dict[str, Page] = {page.slug: page for page in PAGES}
