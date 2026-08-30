"""Job-posting analysis: turn a posting into a prioritised requirements list,
and move that list to/from the annotated ``emphasis`` text the writer pages
consume.

The analysis itself is LLM domain logic and belongs in its own capability
module (``job-post-analyst``), consumed here as a pinned git dependency the
same way ``cover-letter-writer`` is. That repo does not exist yet, so
:func:`analyse` returns a **placeholder** ``Analysis`` for now — enough to
build and click through the whole flow. When the capability lands:

    from job_post_analyst import Input, run
    ...
    output = run(Input(posting=posting))

and this module keeps only the formatting/parsing helpers.

Annotated emphasis text — one block per requirement, blank line between:

    Show you can own pricing and P&L conversations with executives
    > comfortable owning pricing and P&L discussions with C-level stakeholders
    - Led the 2022 pricing rework but never presented directly to C-level

    * a plain line       -> the requirement (the instruction to the writer)
    * a ">" line         -> the exact span of the posting it is anchored to
    * a "-" line         -> the candidate's own note (added by hand after analysis)

A block with no ">"/"-" markers is read as one requirement per plain line,
so a hand-typed "one point per line" list still works unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Cost:
    usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0


@dataclass(frozen=True)
class Requirement:
    point: str  # the requirement phrased as an instruction to the letter / CV
    quote: str  # the exact span of the posting this is anchored to
    importance: str = "strong"  # "must-have" | "strong" | "nice-to-have"
    rationale: str = ""  # one line: why the hiring manager weights this


@dataclass(frozen=True)
class Analysis:
    requirements: list[Requirement] = field(default_factory=list)
    summary: str = ""
    cost: Cost = field(default_factory=Cost)


@dataclass(frozen=True)
class EmphasisPoint:
    """One parsed requirement, ready to become a capability ``Emphasis``.

    ``point`` already has the candidate's note folded in (v1: the
    ``cover-letter-writer`` / ``cv-writer`` contract has no dedicated
    ``candidate_note`` field yet)."""

    point: str
    quote: str | None = None


# --- the analysis step (placeholder until job-post-analyst exists) --------

_PLACEHOLDER_NOTE = (
    "_(Placeholder analysis — the `job-post-analyst` capability isn't wired up "
    "yet. Once it is, this list is written by the model from the posting.)_"
)


def analyse(posting: str) -> Analysis:
    """Analyse a job posting into a prioritised requirements list.

    PLACEHOLDER: returns a fixed, illustrative list regardless of input.
    Swap the body for ``job_post_analyst.run(Input(posting=posting))`` when
    that capability is published and pinned.
    """
    first_line = next((ln.strip() for ln in posting.splitlines() if ln.strip()), "the role")
    reqs = [
        Requirement(
            point="Lead with evidence you can do the core job named in the posting",
            quote=first_line[:200],
            importance="must-have",
            rationale="The headline responsibility — everything else is read against it.",
        ),
        Requirement(
            point="Show measurable outcomes, not just responsibilities",
            quote="track record of delivering results",
            importance="strong",
            rationale="Hiring managers discount duties; numbers and before/after land.",
        ),
        Requirement(
            point="Demonstrate you can work across teams and influence without authority",
            quote="work closely with cross-functional stakeholders",
            importance="strong",
            rationale="Signals the role is matrixed and collaboration is a real risk.",
        ),
        Requirement(
            point="Address the seniority/scope bar directly (team size, budget, ambiguity)",
            quote="operate with autonomy in a fast-moving environment",
            importance="strong",
            rationale="They've been burned by someone who needed too much direction.",
        ),
        Requirement(
            point="Name the domain and show you understand its constraints",
            quote="experience in a regulated / high-growth / enterprise context",
            importance="nice-to-have",
            rationale="A shortlist tiebreaker rather than a gate.",
        ),
    ]
    return Analysis(
        requirements=reqs,
        summary=(
            f"This employer is hiring for {first_line[:120]!r}. "
            + _PLACEHOLDER_NOTE
        ),
        cost=Cost(),
    )


# --- format / parse -----------------------------------------------------------


def requirements_to_emphasis_text(analysis: Analysis) -> str:
    """Render an analysis into the annotated ``emphasis`` textarea format,
    leaving an empty ``- `` line under each block for the candidate's note."""
    blocks: list[str] = []
    for req in analysis.requirements:
        lines = [f"[{req.importance}] {req.point}" if req.importance else req.point]
        if req.quote:
            lines.append(f"> {req.quote}")
        lines.append("- ")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _strip_tag(text: str) -> str:
    """Drop a leading ``[must-have]`` / ``[strong]`` / ``[nice-to-have]`` tag."""
    if text.startswith("[") and "]" in text:
        return text.split("]", 1)[1].strip()
    return text


def parse_annotated_emphasis(text: str) -> list[EmphasisPoint]:
    """Parse the annotated ``emphasis`` text into points for a capability.

    Blank lines separate blocks. Within a block, ``>`` lines are the quoted
    span and ``-`` lines are the candidate's note. A block with neither is
    treated as one requirement per plain line (hand-typed lists still work).
    """
    points: list[EmphasisPoint] = []
    blocks = [b for b in _split_blocks(text)]
    for block in blocks:
        plain: list[str] = []
        quotes: list[str] = []
        notes: list[str] = []
        for raw in block:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                quotes.append(line[1:].strip().strip('"').strip())
            elif line.startswith("- ") or line == "-":
                notes.append(line[1:].strip())
            else:
                plain.append(_strip_tag(line))

        if not quotes and not notes:
            points.extend(EmphasisPoint(point=p) for p in plain if p)
            continue

        requirement = " ".join(p for p in plain if p).strip()
        if not requirement:
            continue
        note = " ".join(n for n in notes if n).strip()
        quote = " ".join(q for q in quotes if q).strip() or None
        point = requirement
        if note:
            point = f"{requirement}\n\nCandidate note: {note}"
        points.append(EmphasisPoint(point=point, quote=quote))
    return points


def _split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw in (text or "").splitlines():
        if raw.strip():
            current.append(raw)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks
