"""Page for the `cover-letter-writer` capability (pinned at v0.10.0).

Maps the capability's contract to a form. Optional contract inputs that
aren't exposed yet: `previous_draft` / `previous_feedback` (the revision
loop needs the prior output carried back — a later addition) and the
operator-config inputs `house_style` / `expert_guidance`.
"""

from __future__ import annotations

from pathlib import Path

from cover_letter_writer import Cost, Emphasis, Input, Output, run

from dashboard.pages._spec import Field, FormReader, Page, RunMeta, Section

# The pinned tag, kept in step with `[tool.uv.sources]` in pyproject.toml.
# Stamped onto every RunMeta so usage records say which build produced them.
CAPABILITY = "cover-letter-writer"
CAPABILITY_VERSION = "v0.10.0"

# Demo inputs, vendored into this repo (a neutralised, shortened real
# posting + a matching fictional CV). They belong to the page, not the
# capability — the capability's own examples aren't part of its contract
# and aren't in the installed package. Swap `cv.md` for your own CV to
# make "Load example" produce a letter you'd actually send.
_EXAMPLES = Path(__file__).parent / "_examples" / "cover_letter_writer"

FIELDS = (
    Field(
        "job_posting",
        "Job posting",
        widget="textarea",
        required=True,
        help="The full posting text — title, company, responsibilities, requirements.",
    ),
    Field(
        "cv",
        "CV",
        widget="textarea",
        required=True,
        help="Plain text. Convert a PDF or DOCX to text first.",
    ),
    Field(
        "job_title",
        "Role title",
        widget="text",
        help="Optional. Only if it isn't obvious from the posting.",
    ),
    Field(
        "job_company",
        "Company",
        widget="text",
        help="Optional. Only if it isn't obvious from the posting.",
    ),
    Field(
        "tone",
        "Tone",
        widget="text",
        help="Optional. e.g. warm, formal, direct. Free text.",
    ),
    Field(
        "emphasis",
        "Points to emphasise",
        widget="lines",
        help="Optional. One point per line, most important first.",
    ),
    Field(
        "background_documents",
        "Background notes",
        widget="textarea",
        help="Optional. Portfolio notes, a bio, answers to application questions, "
        "company-context notes — anything beyond the CV. Treated as one document.",
    ),
    Field(
        "max_words",
        "Max words",
        widget="number",
        help="Optional. Soft length limit for the letter body.",
    ),
    Field(
        "salary_expectation",
        "Salary expectation",
        widget="number",
        help="Optional. A bare number. When set, the letter states it in the close.",
    ),
    Field(
        "availability",
        "Availability",
        widget="text",
        help="Optional. e.g. \"3 months' notice\", \"available immediately\".",
    ),
)

EXAMPLE_FORM = {
    "job_posting": (_EXAMPLES / "job_posting.md").read_text(),
    "cv": (_EXAMPLES / "cv.md").read_text(),
    "emphasis": (_EXAMPLES / "emphasis.md").read_text(),
    "tone": "measured",
    "max_words": "350",
}

EXAMPLE_OUTPUT = Output(
    cover_letter=(
        "Dear Hiring Team,\n\n"
        "I want to apply for the Product Lead role at your company.\n\n"
        "_(Example output. The real letter is written by the capability when you "
        "run it against a live API key.)_\n"
    ),
    targeting_note=(
        "- **Fix activation and retention** — answered with the onboarding redesign "
        "that lifted first-session completion from 48% to 82%.\n"
        "- **Hands-on AI/ML product experience** — the retrieval-based assistant "
        "feature and its adoption numbers.\n"
        "- **Grow a small team** — 4 to 11, including hiring PMs and setting process.\n"
        "- **Not covered by the CV:** direct pricing / P&L advisory to C-level.\n"
    ),
    cost=Cost(
        usd=0.0123,
        input_tokens=1024,
        output_tokens=612,
        cache_read_input_tokens=0,
        cache_write_input_tokens=1500,
    ),
)


def build_input(form) -> Input:
    r = FormReader(form)
    job_posting = r.text("job_posting", "Job posting", required=True)
    cv = r.text("cv", "CV", required=True)
    job_title = r.text("job_title", "Role title")
    job_company = r.text("job_company", "Company")
    tone = r.text("tone", "Tone")
    emphasis = [Emphasis(point=point) for point in r.lines("emphasis")]
    background = r.text("background_documents", "Background notes")
    max_words = r.integer("max_words", "Max words")
    salary_expectation = r.integer("salary_expectation", "Salary expectation")
    availability = r.text("availability", "Availability")
    r.done()
    return Input(
        job_posting=job_posting,
        cv=cv,
        job_title=job_title,
        job_company=job_company,
        tone=tone,
        emphasis=emphasis,
        background_documents=[background] if background else [],
        max_words=max_words,
        salary_expectation=salary_expectation,
        availability=availability,
    )


def sections(output: Output) -> list[Section]:
    return [
        Section("Cover letter", output.cover_letter),
        Section("What it targeted", output.targeting_note),
    ]


def run_meta(output: Output) -> RunMeta:
    cost = output.cost
    return RunMeta(
        capability=CAPABILITY,
        capability_version=CAPABILITY_VERSION,
        cost_usd=cost.usd,
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        cache_read_input_tokens=cost.cache_read_input_tokens,
        cache_write_input_tokens=cost.cache_write_input_tokens,
    )


PAGE = Page(
    slug="cover-letter-writer",
    title="Cover Letter Writer",
    summary="A tailored cover letter from a job posting and your CV, plus a note on what it targeted.",
    fields=FIELDS,
    example_form=EXAMPLE_FORM,
    example_output=EXAMPLE_OUTPUT,
    build_input=build_input,
    run=run,
    sections=sections,
    run_meta=run_meta,
)
