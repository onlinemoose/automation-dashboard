"""Page for the `cover-letter-writer` capability (pinned at v0.9.0).

Maps the capability's contract to a form. Optional contract inputs that
aren't exposed yet: `previous_draft` / `previous_feedback` (the revision
loop needs the prior output carried back — a later addition) and the
operator-config inputs `house_style` / `expert_guidance`.
"""

from __future__ import annotations

from cover_letter_writer import Emphasis, Input, Output, run

from dashboard.pages._spec import Field, FormReader, Page, Section

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
    "job_posting": (
        "Senior Backend Engineer — Acme Payments\n\n"
        "You will own our payments service end to end: the ledger, reconciliation, "
        "and the partner API. We run Python and Postgres. Experience with double-entry "
        "accounting systems and high-volume transaction data is a strong plus."
    ),
    "cv": (
        "Eight years building payment systems in Python. At Fintech Co I led the "
        "migration to Stripe and rebuilt the double-entry ledger, cutting monthly "
        "reconciliation breaks by 90%. Deep Postgres experience, including partitioning "
        "transaction tables past 500M rows and tuning the reconciliation queries."
    ),
    "job_company": "Acme Payments",
    "tone": "measured",
    "emphasis": "lead with the ledger rebuild\nname the reconciliation numbers",
    "max_words": "300",
}

EXAMPLE_OUTPUT = Output(
    cover_letter=(
        "Dear Hiring Team,\n\n"
        "I want to apply for the Senior Backend Engineer role at Acme Payments.\n\n"
        "_(Example output. The real letter is written by the capability when you run it.)_\n"
    ),
    targeting_note=(
        "- **Own the payments service end to end** — answered with the Fintech Co "
        "ledger rebuild and Stripe migration.\n"
        "- **Python and Postgres** — covered directly.\n"
        "- **Double-entry accounting / high-volume data** — covered (90% fewer "
        "reconciliation breaks, 500M-row partitioning).\n"
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
)
