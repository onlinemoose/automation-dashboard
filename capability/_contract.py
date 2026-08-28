"""The shapes of what goes in and what comes out.

A "type" here just means: the written, named shape of a piece of data —
so the computer (and the next reader) can see exactly what's expected,
instead of everything passing loose bags of values around.

Keep this file small and readable; it mirrors docs/CONTRACT.md. If you
want incoming data validated automatically, swap these dataclasses for
Pydantic models — the rest of the module doesn't change.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Input:
    """Everything run() needs. Required fields first, optional after."""

    # --- required ---
    text: str  # TODO: replace with this module's real required inputs

    # --- optional: must have a default; the module works without them ---
    notes: str | None = None
    emphasis: list[str] = field(default_factory=list)


@dataclass
class Output:
    """Everything run() hands back."""

    result: str  # TODO: replace with this module's real output shape
    rationale: str = ""  # short "what I did / what I targeted" note for the caller
