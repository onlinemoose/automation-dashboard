"""The `content-creation-team` capability, consumed at an allowed seam
(CLAUDE.md rule 5) — the same way `job-analyst` and `targeted-editor` are.

`content_creation_team.run()` researches, drafts, edits and SEO-reviews
one finished piece of copy from a `goal` + `content_brief`. This module
builds its `Input` from plain values, exposes `run` as the one call into
it, and maps the `Output` onto the app's own shapes for storage and
display. It needs `ANTHROPIC_API_KEY` in the environment (CLAUDE.md rule
7). The page's `run()` is `run` here; the page's `sections` / `run_meta`
read the raw `Output` directly, like `cv_writer`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from importlib import metadata

import content_creation_team

CAPABILITY = "content-creation-team"


def capability_version() -> str:
    """The installed `content-creation-team` version, for the metadata footer."""
    try:
        return "v" + metadata.version(CAPABILITY)
    except metadata.PackageNotFoundError:  # pragma: no cover - always installed in practice
        return "(unknown)"


@dataclass(frozen=True)
class Feedback:
    """One human note on the previous draft, for a "send back to the team"
    pass. `quote`, when present, is the exact span it is about."""

    comment: str
    quote: str | None = None


def _n(value: str | None) -> str | None:
    """A trimmed string, or None when empty — the contract wants None, not ''."""
    value = (value or "").strip()
    return value or None


def build_input(
    *,
    goal: str,
    content_brief: str,
    topic_areas: Iterable[str] = (),
    audience: str | None = None,
    audience_brief: str | None = None,
    target_length_words: int | None = None,
    call_to_action: str | None = None,
    target_keywords: Iterable[str] = (),
    house_style: str | None = None,
    max_usd: float = 2.0,
    max_editor_revisions: int = 5,
    max_seo_revisions: int = 3,
    research_notes: str | None = None,
    seo_brief: str | None = None,
    previous_draft: str | None = None,
    previous_feedback: Sequence[Feedback] = (),
) -> "content_creation_team.Input":
    """The one place a `content_creation_team.Input` is built — from the
    page form (fresh run) and from the send-back route (revision run)."""
    return content_creation_team.Input(
        goal=goal,
        content_brief=content_brief,
        topic_areas=list(topic_areas),
        audience=_n(audience),
        audience_brief=_n(audience_brief),
        target_length_words=target_length_words,
        call_to_action=_n(call_to_action),
        target_keywords=list(target_keywords),
        house_style=_n(house_style),
        max_usd=max_usd,
        max_editor_revisions=max_editor_revisions,
        max_seo_revisions=max_seo_revisions,
        research_notes=_n(research_notes),
        seo_brief=_n(seo_brief),
        previous_draft=previous_draft,
        previous_feedback=[
            content_creation_team.Feedback(comment=f.comment, quote=f.quote)
            for f in previous_feedback
        ],
    )


def run(data: "content_creation_team.Input") -> "content_creation_team.Output":
    """The single call into the capability's front door. A thin wrapper
    (not `run = content_creation_team.run`) so the attribute lookup
    happens at call time — a test can monkeypatch `content_creation_team.run`."""
    return content_creation_team.run(data)


def cost_meta(output: "content_creation_team.Output") -> dict:
    """The 7-field cost-meta dict stored on `piece.meta`."""
    c = output.cost
    return {
        "capability": CAPABILITY,
        "capability_version": capability_version(),
        "cost_usd": float(c.usd),
        "input_tokens": c.input_tokens,
        "output_tokens": c.output_tokens,
        "cache_read_input_tokens": c.cache_read_input_tokens,
        "cache_write_input_tokens": c.cache_write_input_tokens,
    }
