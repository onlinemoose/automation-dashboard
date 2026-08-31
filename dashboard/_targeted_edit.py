"""Targeted revision: rewrite one selected span of a draft, given an
instruction and the surrounding draft as context.

The revision itself is LLM domain logic and lives in its own capability
module, ``targeted-editor`` (imported as ``targeted_editor``), consumed
here the same way ``job-analyst`` is. :func:`revise` calls its ``run()``
front door and maps the ``Output`` onto this app's ``Revision`` shape. It
needs ``ANTHROPIC_API_KEY`` in the environment (CLAUDE.md rule 7).

The splice, the linear history, and undo-by-replay are the app's own and
live in ``dashboard/_drafts.py`` — this module is only the capability
call at an allowed seam (CLAUDE.md rule 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata

import targeted_editor

CAPABILITY = "targeted-editor"

# Dashboard Output-section slug -> the capability's ``kind`` steer. A
# section that isn't a writer's prose (e.g. "targeting-note") stays on
# the neutral "prose" default.
_KIND_FOR_SECTION = {
    "cover-letter": "cover_letter",
    "cover letter": "cover_letter",
    "cv": "cv",
    "curriculum-vitae": "cv",
}


@dataclass(frozen=True)
class Cost:
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "usd": self.usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "cache_write_input_tokens": self.cache_write_input_tokens,
        }


@dataclass(frozen=True)
class Revision:
    """A proposed replacement for one span — shown as a diff, not yet
    spliced into the draft."""

    revised: str
    note: str
    cost: Cost = field(default_factory=Cost)


def kind_for_section(section: str) -> str:
    return _KIND_FOR_SECTION.get((section or "").strip().lower(), "prose")


def capability_version() -> str:
    """The installed ``targeted-editor`` version, for the run-metadata footer."""
    try:
        return "v" + metadata.version(CAPABILITY)
    except metadata.PackageNotFoundError:  # pragma: no cover - always installed in practice
        return "(unknown)"


def revise(document: str, selection: str, instruction: str, *, kind: str = "prose") -> Revision:
    """Revise one span of ``document``. Calls the ``targeted-editor``
    capability (one LLM call) and maps its ``Output`` onto this app's
    ``Revision``. Anthropic SDK errors (auth, rate limit) propagate; the
    capability raises ``ValueError`` for bad input and ``RuntimeError``
    if the model ignored the "span only" rule."""
    out = targeted_editor.run(
        targeted_editor.Input(
            document=document,
            selection=selection,
            instruction=instruction,
            kind=kind,
        )
    )
    c = out.cost
    return Revision(
        revised=out.revised,
        note=out.note,
        cost=Cost(
            usd=c.usd,
            input_tokens=c.input_tokens,
            output_tokens=c.output_tokens,
            cache_read_input_tokens=c.cache_read_input_tokens,
            cache_write_input_tokens=c.cache_write_input_tokens,
        ),
    )
