"""Adapter for the `publish-to-website` capability, consumed at an
allowed seam (CLAUDE.md rule 5) — the same way `content_creation_team`
and `targeted_editor` are.

`publish_to_website.run()` turns a finished piece (title / excerpt /
slug / tags + final copy) into the two commit-ready files for the
Feldklang repo: the `.mdx` post and the optimised hero JPEG. This module
builds its `Input` from a brief's stored `piece` (with the publish
form's overrides layered on top), exposes `run` as the one call into it,
and maps its `Output` onto the 7-field cost-meta dict for the result
footer. Committing those files to a live repo is `_feldklang_repo.py`'s
job, not this module's or the capability's (CLAUDE.md rule 2: a
capability receives and returns, it never fetches or pushes).
"""

from __future__ import annotations

from importlib import metadata

import publish_to_website

CAPABILITY = "publish-to-website"

# The Feldklang brand Recraft style_id (plan A6). Created 2026-09-10 from
# five design-system reference compositions (warm paper / ink / terracotta,
# paper grain, generous negative space); in an A/B against prompt-only it
# held the palette (~75% paper ground vs ~6%) and the editorial restraint,
# so it's the default. See publish-to-website/docs/PROGRESS.md.
DEFAULT_RECRAFT_STYLE_ID: str | None = "f5c10ae2-c95d-4ea6-b5db-542762fab62f"


def capability_version() -> str:
    """The installed `publish-to-website` version, for the metadata footer."""
    try:
        return "v" + metadata.version(CAPABILITY)
    except metadata.PackageNotFoundError:  # pragma: no cover - always installed in practice
        return "(unknown)"


def _n(value: object) -> str | None:
    """A trimmed string, or None when empty/absent."""
    text = str(value or "").strip()
    return text or None


def build_input(
    piece: dict, *, overrides: dict | None = None
) -> "publish_to_website.Input":
    """The one place a `publish_to_website.Input` is built — from a
    brief's stored `piece` (routes.py's `_piece_payload`), with the
    publish form's overrides (title/excerpt/slug/tags/image_prompt)
    applied on top. Any override left blank falls back to the piece's
    own value."""
    overrides = overrides or {}

    def pick(key: str, fallback: str) -> str:
        value = _n(overrides.get(key))
        return value if value is not None else fallback

    tags = overrides.get("tags")
    if tags is None:
        tags = list(piece.get("tags") or [])

    return publish_to_website.Input(
        title=pick("title", str(piece.get("title") or "")),
        excerpt=pick("excerpt", str(piece.get("excerpt") or "")),
        slug=pick("slug", str(piece.get("slug") or "")),
        tags=list(tags),
        body_markdown=str(piece.get("final_copy") or ""),
        image_prompt=_n(overrides.get("image_prompt")),
        recraft_style_id=DEFAULT_RECRAFT_STYLE_ID,
    )


def run(data: "publish_to_website.Input") -> "publish_to_website.Output":
    """The single call into the capability's front door. A thin wrapper
    (not `run = publish_to_website.run`) so the attribute lookup happens
    at call time — a test can monkeypatch `publish_to_website.run`."""
    return publish_to_website.run(data)


def cost_meta(output: "publish_to_website.Output") -> dict:
    """The 7-field cost-meta dict stored on `piece["published"]`'s run
    record. The capability makes no LLM call, so the token fields are
    always 0 — only `cost_usd` (the Recraft list price) is meaningful."""
    c = output.cost
    return {
        "capability": CAPABILITY,
        "capability_version": capability_version(),
        "cost_usd": float(c.usd),
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_write_input_tokens": 0,
    }
