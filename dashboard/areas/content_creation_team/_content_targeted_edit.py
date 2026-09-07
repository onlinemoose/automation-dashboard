"""Targeted revision of one span of a finished piece — the same
`targeted-editor` capability the Job Application area uses, consumed here
at an allowed seam (CLAUDE.md rule 5).

A self-contained copy of `dashboard/_targeted_edit.py`: an area owns its
span editor rather than importing another area's. The splice, the linear
history, and undo-by-replay live in `_content_drafts.py`; this module is
only the capability call. It needs `ANTHROPIC_API_KEY` in the environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata

import targeted_editor

CAPABILITY = "targeted-editor"

# The only editable section a content piece has is the finished copy —
# plain prose, which is `targeted-editor`'s neutral default kind anyway.
_KIND_FOR_SECTION = {"final-copy": "prose"}


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
    """The installed `targeted-editor` version, for the metadata footer."""
    try:
        return "v" + metadata.version(CAPABILITY)
    except metadata.PackageNotFoundError:  # pragma: no cover
        return "(unknown)"


def revise(
    document: str, selection: str, instruction: str, *, kind: str = "prose"
) -> Revision:
    """Revise one span of `document`. One LLM call via the `targeted-editor`
    front door. Anthropic SDK errors propagate; the capability raises
    `ValueError` for bad input and `RuntimeError` if the model ignored the
    "span only" rule."""
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
