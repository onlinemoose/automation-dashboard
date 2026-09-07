"""Page for the `content-creation-team` capability (pinned at v0.1.0).

Maps the capability's contract to a form. The page is always entered from
a saved Content brief (`/content/{id}` → "Run the content team"), so the
brief id rides along hidden and `build_input` resolves the whole brief;
the raw fields are the fallback the generic offline test and `?example=`
path use. Operator caps (`max_usd`, `max_editor_revisions`,
`max_seo_revisions`) and the "send back to the team" resume inputs
(`previous_draft` / `previous_feedback` / `research_notes` / `seo_brief`)
are handled by the area's own routes, not this form.
"""

from __future__ import annotations

from pathlib import Path

from content_creation_team import Cost, Output, RevisionRound

from dashboard.areas.content_creation_team import _briefs, _content_team
from dashboard.pages._spec import Field, FormReader, Page, RunMeta, Section

# The pinned tag, kept in step with `[tool.uv.sources]` in pyproject.toml.
# Stamped onto every RunMeta so usage records say which build produced them.
CAPABILITY = "content-creation-team"
CAPABILITY_VERSION = "v0.1.0"

# Demo inputs, vendored into this repo (copied from the capability's own
# examples/, which aren't part of its installed package or contract).
_EXAMPLES = Path(__file__).parent / "_examples" / "content_creation_team"

# A vendored snapshot of the capability's bundled default house style —
# the text `house_style` replaces wholesale. The brief form offers it
# behind an "insert the bundled default" link so an operator can trim it
# down rather than write one from scratch. Not part of the contract; it
# drifts if the capability changes its default, the same way the demo
# inputs above do.
DEFAULT_HOUSE_STYLE = (_EXAMPLES / "house_style_default.md").read_text()


FIELDS = (
    Field(
        # This page is always opened from a Content brief; the id rides
        # along hidden. A bare visit redirects to /content.
        "content_brief_id",
        "Content brief",
        widget="hidden",
    ),
    Field(
        "goal",
        "Goal",
        widget="textarea",
        required=True,
        help="What the piece has to achieve — the purpose it serves, not just "
        "its subject.",
    ),
    Field(
        "content_brief",
        "Content brief",
        widget="textarea",
        required=True,
        help="The substance: a prose-and-bullets summary of what the piece must "
        "contain — the angle, the key points, the shape of the argument, any "
        "structure to follow.",
    ),
    Field(
        "topic_areas",
        "Topic areas",
        widget="lines",
        help="Optional. One categorisation tag per line.",
    ),
    Field(
        "audience",
        "Audience",
        widget="text",
        help='Optional. A persona label, e.g. "Engineering managers".',
    ),
    Field(
        "audience_brief",
        "Audience brief",
        widget="textarea",
        help="Optional. Enriched detail about that audience, if you have it.",
    ),
    Field(
        "target_length_words",
        "Target length (words)",
        widget="number",
        help="Optional. A rough finished length — a soft target, not a hard cut.",
    ),
    Field(
        "call_to_action",
        "Call to action",
        widget="textarea",
        help="Optional. What the ending should turn the reader toward — an "
        "offering, resource, or next step, in your own words.",
    ),
    Field(
        "target_keywords",
        "Target keywords",
        widget="lines",
        help="Optional. One SEO keyword per line — a steer for the SEO brief "
        "stage, not a mechanical check.",
    ),
    Field(
        "house_style",
        "House style",
        widget="textarea",
        help="Optional. How the prose should read: register, spelling/locale, "
        "date format, punctuation defaults. Replaces the bundled default "
        "wholesale when set.",
    ),
)


EXAMPLE_FORM = {
    "goal": (_EXAMPLES / "goal.md").read_text(),
    "content_brief": (_EXAMPLES / "brief.md").read_text(),
    "target_length_words": "1100",
}


EXAMPLE_OUTPUT = Output(
    final_copy=(
        "# The meeting that went quiet\n\n"
        "The proposal used to draw questions. Now it draws nods.\n\n"
        "_(Example output. The real piece is written by the content team when "
        "you run it against a live API key.)_\n"
    ),
    title="The meeting that went quiet: why your team stopped pushing back",
    excerpt=(
        "New managers mistake silence for agreement. It is usually the sound of "
        "a team that has decided disagreeing with you isn't worth the effort."
    ),
    slug="meeting-went-quiet-team-stopped-pushing-back",
    tags=["engineering management", "psychological safety", "decision-making"],
    approved=True,
    stopped_on="approved",
    research_notes=(
        "- New-manager failure-rate figures vary widely by source; flag any not "
        "traceable to a named study.\n"
        "- Psychological-safety literature (Edmondson) frames dissent as "
        "information, not friction.\n"
    ),
    seo_brief=(
        "Primary intent: a first-time engineering manager searching for why "
        "their team has gone quiet in meetings. Secondary: how to encourage "
        "dissent without theatre.\n"
    ),
    editor_notes=(
        "Round 2: tightened the open to lead with the symptom; the close now "
        "lands the reframe as an earned turn rather than a summary.\n"
    ),
    seo_notes=(
        "Title and H2s carry the primary term; excerpt is within 155 "
        "characters; slug is clean.\n"
    ),
    revision_history=[
        RevisionRound(
            round=1,
            draft="(first draft)",
            editor_verdict="revise",
            editor_notes="The open is a scene-set; lead with the finding instead.",
            seo_verdict=None,
            seo_notes=None,
        ),
        RevisionRound(
            round=2,
            draft="(second draft)",
            editor_verdict="approved",
            editor_notes="Approved — the argument now earns its close.",
            seo_verdict="approved",
            seo_notes="Approved — search intent is well covered.",
        ),
    ],
    cost=Cost(
        usd=0.42,
        input_tokens=48000,
        output_tokens=9000,
        cache_read_input_tokens=120000,
        cache_write_input_tokens=16000,
    ),
)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def build_input(form, user_id: str):
    r = FormReader(form)
    # `content_brief_id` is a key into the app's own Content briefs store
    # (like `job_post_id` on the writer pages), not a contract argument.
    # When set it carries the whole brief — every knob, and the operator
    # caps. That store is per-user, hence `user_id`; it never reaches `Input`.
    brief_id = r.text("content_brief_id", "Content brief")
    brief = _briefs.get_brief(brief_id, user_id) if brief_id else None
    if brief is not None:
        kwargs = brief_kwargs(brief)
    else:
        goal = r.text("goal", "Goal", required=True)
        content_brief = r.text("content_brief", "Content brief", required=True)
        kwargs = dict(
            goal=goal or "",
            content_brief=content_brief or "",
            topic_areas=r.lines("topic_areas"),
            audience=r.text("audience", "Audience"),
            audience_brief=r.text("audience_brief", "Audience brief"),
            target_length_words=r.integer("target_length_words", "Target length (words)"),
            call_to_action=r.text("call_to_action", "Call to action"),
            target_keywords=r.lines("target_keywords"),
            house_style=r.text("house_style", "House style"),
        )
    r.done()
    return _content_team.build_input(**kwargs)


def brief_kwargs(brief) -> dict:
    """The `_content_team.build_input` kwargs for a saved brief — shared by
    this page and the area's "send back to the team" route."""
    return dict(
        goal=brief.goal,
        content_brief=brief.content_brief,
        topic_areas=_lines(brief.topic_areas),
        audience=brief.audience or None,
        audience_brief=brief.audience_brief or None,
        target_length_words=brief.target_length_words or None,
        call_to_action=brief.call_to_action or None,
        target_keywords=_lines(brief.target_keywords),
        house_style=brief.house_style or None,
        max_usd=brief.max_usd,
        max_editor_revisions=brief.max_editor_revisions,
        max_seo_revisions=brief.max_seo_revisions,
    )


def _metadata_block(o: Output) -> str:
    lines = [
        f"**Title:** {o.title or '—'}",
        f"**Excerpt:** {o.excerpt or '—'}",
        f"**Slug:** `{o.slug or '—'}`",
        f"**Tags:** {', '.join(o.tags) if o.tags else '—'}",
    ]
    if not o.approved:
        lines.insert(
            0,
            f"> ⚠ **Shipped without full approval** — the run stopped on "
            f"`{o.stopped_on}`. Title / excerpt / slug / tags may be empty.",
        )
    return "\n\n".join(lines)


def _revision_history(o: Output) -> str:
    rounds = []
    for rd in o.revision_history:
        seo = rd.seo_verdict or "— (editor did not approve this round)"
        rounds.append(
            f"### Round {rd.round}\n\n"
            f"**Editor:** {rd.editor_verdict}\n\n{rd.editor_notes or '—'}\n\n"
            f"**SEO review:** {seo}\n\n{rd.seo_notes or '—'}"
        )
    return "\n\n".join(rounds) or "_(no rounds recorded)_"


def sections(output: Output) -> list[Section]:
    return [
        Section("Publishing metadata", _metadata_block(output), editable=False),
        # The one section opened as a working draft for span edits.
        Section("Final copy", output.final_copy, editable=True),
        Section("SEO brief", output.seo_brief or "_(none)_", editable=False),
        Section("Editor notes", output.editor_notes or "_(none)_", editable=False),
        Section("SEO review notes", output.seo_notes or "_(none)_", editable=False),
        # Read-only, but surfaced so the operator can see what a revision
        # run will carry forward (and download it).
        Section("Research notes", output.research_notes or "_(none)_", editable=False),
        Section("Revision history", _revision_history(output), editable=False),
    ]


def run_meta(output: Output) -> RunMeta:
    cost = output.cost
    return RunMeta(
        capability=CAPABILITY,
        capability_version=CAPABILITY_VERSION,
        cost_usd=float(cost.usd),
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        cache_read_input_tokens=cost.cache_read_input_tokens,
        cache_write_input_tokens=cost.cache_write_input_tokens,
    )


PAGE = Page(
    slug="content-creation-team",
    title="Content Creation Team",
    summary=(
        "Research, draft, edit and SEO-review one finished piece of copy from a "
        "goal and a brief, plus the reviewer notes and revision history."
    ),
    fields=FIELDS,
    example_form=EXAMPLE_FORM,
    example_output=EXAMPLE_OUTPUT,
    build_input=build_input,
    run=_content_team.run,  # == content_creation_team.run
    sections=sections,
    run_meta=run_meta,
    # SEO brief -> research -> (copywrite -> edit -> SEO review), looping.
    # First live runs are ~4 minutes.
    slow=True,
    # The contract has no `on_progress` callback — the holding view stays a
    # spinner, no live word count.
    progress=False,
    # Persistence is the area's own /content/{id}/run route (onto the
    # Content brief's `piece`), not a job_posts column.
    saved_result_slot=None,
)
