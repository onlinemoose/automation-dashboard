"""Job-posting analysis: turn a posting into a prioritised requirements list,
and move that list to/from the annotated ``emphasis`` text the writer pages
consume.

The analysis itself is LLM domain logic and lives in its own capability
module, ``job-analyst`` (imported as ``job_analyst``), consumed here the
same way ``cover-letter-writer`` is. :func:`analyse` calls its ``run()``
front door and maps the ``Output`` onto this app's ``Analysis`` shape — the
capability's four-value importance scale collapses to the dashboard's
three, and ``reading_between_the_lines`` is folded into the summary. It
needs ``ANTHROPIC_API_KEY`` in the environment (CLAUDE.md rule 7); the rest
of this module is just formatting/parsing helpers.

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
from importlib import metadata

import job_analyst


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
    company: str = ""  # hiring company, as written in the posting; "" if unstated
    job_title: str = ""  # role title, as written in the posting; "" if unstated
    cost: Cost = field(default_factory=Cost)


@dataclass(frozen=True)
class EmphasisPoint:
    """One parsed requirement, ready to become a capability ``Emphasis``.

    ``point`` already has the candidate's note folded in (v1: the
    ``cover-letter-writer`` / ``cv-writer`` contract has no dedicated
    ``candidate_note`` field yet)."""

    point: str
    quote: str | None = None


@dataclass(frozen=True)
class EmphasisItem:
    """One requirement as shown in the structured emphasis editor: the
    analysis output (``requirement`` / ``quote`` / ``importance``, read-only)
    plus the candidate's editable ``note``. Round-trips to and from the
    annotated ``emphasis`` text via :func:`parse_emphasis_items` /
    :func:`emphasis_items_to_text`."""

    requirement: str
    quote: str = ""
    importance: str = ""  # "" | "must-have" | "strong" | "nice-to-have"
    note: str = ""


# --- the analysis step (the job-analyst capability) ----------------------

# job-analyst ranks on "critical" | "high" | "medium" | "low"; the
# dashboard's emphasis list has three tiers. "high" and "medium" both land
# on "strong" — the distinction that matters downstream is gate vs.
# not-a-gate.
_IMPORTANCE = {
    "critical": "must-have",
    "high": "strong",
    "medium": "strong",
    "low": "nice-to-have",
}


def capability_version() -> str:
    """The installed ``job-analyst`` version, for the run-metadata footer."""
    try:
        return "v" + metadata.version("job-analyst")
    except metadata.PackageNotFoundError:  # pragma: no cover - always installed in practice
        return "(unknown)"


def analyse(posting: str) -> Analysis:
    """Analyse a job posting into a prioritised requirements list.

    Calls the ``job-analyst`` capability (one LLM call) and maps its
    ``Output`` onto this app's ``Analysis``. Needs ``ANTHROPIC_API_KEY`` in
    the environment. Anthropic SDK errors (auth, rate limit) propagate.
    """
    return _to_analysis(job_analyst.run(job_analyst.Input(posting=posting)))


def _to_analysis(output: job_analyst.Output) -> Analysis:
    reqs = [
        Requirement(
            point=req.point,
            quote=req.quote,
            importance=_IMPORTANCE.get(req.importance, "strong"),
            rationale=req.rationale,
        )
        for req in output.requirements
    ]
    summary = output.summary.rstrip()
    if output.reading_between_the_lines:
        bullets = "\n".join(f"- {line}" for line in output.reading_between_the_lines)
        summary = f"{summary}\n\n**Reading between the lines**\n\n{bullets}"
    c = output.cost
    return Analysis(
        requirements=reqs,
        summary=summary,
        company=output.company,
        job_title=output.job_title,
        cost=Cost(
            usd=c.usd,
            input_tokens=c.input_tokens,
            output_tokens=c.output_tokens,
            cache_read_input_tokens=c.cache_read_input_tokens,
            cache_write_input_tokens=c.cache_write_input_tokens,
        ),
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


_TAGS = ("must-have", "strong", "nice-to-have")


def _strip_tag(text: str) -> str:
    """Drop a leading ``[must-have]`` / ``[strong]`` / ``[nice-to-have]`` tag."""
    if text.startswith("[") and "]" in text:
        return text.split("]", 1)[1].strip()
    return text


def _tag_of(text: str) -> str:
    """The importance tag a plain line leads with, or ``""``."""
    if text.startswith("[") and "]" in text:
        candidate = text[1 : text.index("]")].strip()
        if candidate in _TAGS:
            return candidate
    return ""


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


# --- structured emphasis editor <-> annotated text --------------------------


def parse_emphasis_items(text: str) -> list[EmphasisItem]:
    """Parse the annotated ``emphasis`` text into rows for the structured
    editor. Inverse of :func:`emphasis_items_to_text` for the canonical
    format :func:`requirements_to_emphasis_text` produces. A block with no
    ``>``/``-``/``[tag]`` markers still yields one item per plain line, so a
    hand-typed list degrades to editable rows rather than vanishing."""
    items: list[EmphasisItem] = []
    for block in _split_blocks(text):
        plain: list[str] = []
        quotes: list[str] = []
        notes: list[str] = []
        importance = ""
        for raw in block:
            line = raw.strip()
            if not line:
                continue
            if line.startswith(">"):
                quotes.append(line[1:].strip().strip('"').strip())
            elif line.startswith("- ") or line == "-":
                notes.append(line[1:].strip())
            else:
                importance = importance or _tag_of(line)
                plain.append(_strip_tag(line))

        if not quotes and not notes and not importance:
            items.extend(EmphasisItem(requirement=p) for p in plain if p)
            continue

        requirement = " ".join(p for p in plain if p).strip()
        if not requirement:
            continue
        items.append(
            EmphasisItem(
                requirement=requirement,
                quote=" ".join(q for q in quotes if q).strip(),
                importance=importance,
                note=" ".join(n for n in notes if n).strip(),
            )
        )
    return items


def emphasis_items_to_text(items: list[EmphasisItem]) -> str:
    """Render structured editor rows back into the annotated ``emphasis``
    text — the exact shape :func:`requirements_to_emphasis_text` uses, so the
    stored value and the writer-page parse are unchanged."""
    blocks: list[str] = []
    for it in items:
        req = it.requirement.strip()
        if not req:
            continue
        lines = [f"[{it.importance}] {req}" if it.importance else req]
        if it.quote.strip():
            lines.append(f"> {it.quote.strip()}")
        note = it.note.strip()
        lines.append(f"- {note}" if note else "- ")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + ("\n" if blocks else "")
