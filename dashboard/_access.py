"""Per-user area access control (docs/ACCESS.md).

The dashboard hosts several product areas (docs/AREAS.md); this module
answers "may this user reach this area" from the grant on their
`AuthedUser.areas` (resolved once at sign-in — see `dashboard/_auth.py`).

A small static table maps each area to its nav links, index card, page
slugs and URL prefixes. Job Application stays flat (no `Area` object), so
it is declared here verbatim; every other area's table entry is derived
from its packaged `Area` (`dashboard.pages.AREAS`), read lazily inside an
`lru_cache`d builder so this module never imports an area at module scope
(that would cycle: `dashboard.pages` -> the content area -> its `routes.py`
-> this module).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

from fastapi import HTTPException
from starlette.requests import Request

from dashboard import _auth


@dataclass(frozen=True)
class AreaDecl:
    key: str  # == guardrail manifest key / app_metadata "areas" value
    nav: tuple[tuple[str, str], ...]  # (label, href) pairs for the topbar
    title: str  # index card title
    summary: str  # index card blurb
    slugs: frozenset[str]  # capability page slugs in this area
    prefixes: tuple[str, ...]  # URL path-prefixes this area owns


# Job Application has no packaged `Area` (docs/AREAS.md: "stays flat for
# now"), so it is declared here verbatim. `nav` carries both pairs so a
# full-access user's topbar renders exactly as it did before this module
# existed.
_JOB_APPLICATION = AreaDecl(
    key="job_application",
    nav=(("Job posts", "/jobs"), ("Documents", "/documents")),
    title="Job Application Co-Pilot",  # frozen: test_index_shows_the_copilot_entry
    summary=(
        "Add a job post, analyse what the hiring manager is really weighing, "
        "annotate each point, then build a tailored application from it."
    ),
    slugs=frozenset({"cover-letter-writer", "cv-writer"}),
    prefixes=("/jobs", "/documents", "/drafts"),
)


@functools.lru_cache(maxsize=1)
def _table() -> dict[str, AreaDecl]:
    from dashboard.pages import AREAS  # lazy — breaks the import cycle

    table = {_JOB_APPLICATION.key: _JOB_APPLICATION}
    for area in AREAS:
        first_segments = {"/" + r.strip("/").split("/")[0] for r in area.allowed_routes}
        table[area.name] = AreaDecl(
            key=area.name,
            nav=area.nav,
            title=area.nav[0][0],
            summary=area.summary,
            slugs=frozenset(p.slug for p in area.page_specs),
            prefixes=tuple(sorted(first_segments)),
        )
    return table


def _granted(user: _auth.AuthedUser | None) -> set[str] | None:
    """This user's grant, as a set — `None` means every area."""
    return None if (user is None or user.areas is None) else set(user.areas)


def area_for_path(path: str) -> str | None:
    """The area owning `path`, or `None` for a shell path (always allowed)."""
    for decl in _table().values():
        if any(path == p or path.startswith(p + "/") for p in decl.prefixes):
            return decl.key
    return None


def area_for_slug(slug: str) -> str | None:
    """The area owning this page `slug`, or `None` when no area claims it
    (a shell / unknown slug — the caller decides what that means)."""
    return next((decl.key for decl in _table().values() if slug in decl.slugs), None)


def can_access_path(user: _auth.AuthedUser | None, path: str) -> bool:
    key = area_for_path(path)
    granted = _granted(user)
    return key is None or granted is None or key in granted


def can_access_slug(user: _auth.AuthedUser | None, slug: str) -> bool:
    key = area_for_slug(slug)
    granted = _granted(user)
    return key is None or granted is None or key in granted


def visible_areas(user: _auth.AuthedUser | None) -> list[AreaDecl]:
    """Every area this user may reach, in table order — what the topbar
    nav and the index cards iterate."""
    granted = _granted(user)
    return [decl for decl in _table().values() if granted is None or decl.key in granted]


def require_slug(request: Request, slug: str) -> None:
    """404 when the signed-in user's grant excludes this page's area.

    Call after the `PAGES_BY_SLUG` lookup, so `slug` is always a real
    page — a denied area is invisible, not a 403 (docs/ACCESS.md).
    """
    if not can_access_slug(_auth.current_user(request), slug):
        raise HTTPException(status_code=404)
