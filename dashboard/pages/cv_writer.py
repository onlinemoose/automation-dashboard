"""Page for the `cv-writer` capability (pinned at v0.3.0).

Maps the capability's contract to a form. Optional contract inputs that
aren't exposed yet: `previous_draft` / `previous_feedback` (the revision
loop needs the prior output carried back — a later addition) and the
operator-config inputs `house_style` / `expert_guidance`.
"""

from __future__ import annotations

from pathlib import Path

from cv_writer import Cost, Emphasis, Input, Output, run

from dashboard.pages._spec import Field, FormReader, Page, RunMeta, Section

# The pinned tag, kept in step with `[tool.uv.sources]` in pyproject.toml.
# Stamped onto every RunMeta so usage records say which build produced them.
CAPABILITY = "cv-writer"
CAPABILITY_VERSION = "v0.3.0"

# Demo inputs, vendored into this repo (a neutralised posting + a matching
# fictional CV). They belong to the page, not the capability — the
# capability's own examples aren't part of its contract and aren't in the
# installed package. Swap `cv.md` for your own CV to make "Load example"
# produce a CV you'd actually use.
_EXAMPLES = Path(__file__).parent / "_examples" / "cv_writer"

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
        "Current CV",
        widget="textarea",
        required=True,
        help="Plain text, including the name / contact block at the top. "
        "Convert a PDF or DOCX to text first.",
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
        help="Optional. e.g. conservative, punchy, academic. Free text.",
    ),
    Field(
        "target_length",
        "Target length",
        widget="text",
        help='Optional. Free text, e.g. "1 page", "2 pages". A soft target.',
    ),
    Field(
        "region",
        "Region",
        widget="text",
        help="Optional. CV conventions to follow, e.g. UK, US, Germany. "
        "Defaults to UK.",
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
        help="Optional. Portfolio notes, project write-ups, a bio, older roles "
        "left off the CV, company-context notes — anything beyond the CV. "
        "Treated as one document.",
    ),
)

EXAMPLE_FORM = {
    "job_posting": (_EXAMPLES / "job_posting.md").read_text(),
    "cv": (_EXAMPLES / "cv.md").read_text(),
    "emphasis": (_EXAMPLES / "emphasis.md").read_text(),
    "region": "UK",
    "target_length": "2 pages",
}

EXAMPLE_OUTPUT = Output(
    tailored_cv=(
        "# Priya Nair\n\n"
        "priya.nair@example.com | +44 7700 900123 | Bristol, UK\n\n"
        "## Profile\n\n"
        "Infrastructure engineer with 9 years running backend platforms, the "
        "last 4 on Kubernetes, GitOps delivery, and observability cost.\n\n"
        "_(Example output. The real CV is written by the capability when you "
        "run it against a live API key.)_\n"
    ),
    tailoring_note=(
        "- **Lead a cross-team migration** — the Argo CD / GitOps rollout across "
        "18 teams is now the first bullet of the current role.\n"
        "- **Cut observability cost** — the 40% Datadog reduction (~£28k/month) "
        "moved up and reworded to lead with the saving.\n"
        "- **Own SLOs and incident review** — surfaced near the top of the "
        "Merridale Health role.\n"
        "- **Mentoring** — kept, with the two promotions to senior.\n"
        "- **Service mesh (Istio)** — listed as basic, not oversold.\n"
        "- **Not evidenced:** freight / logistics domain experience.\n"
    ),
    cost=Cost(
        usd=0.0184,
        input_tokens=2048,
        output_tokens=1430,
        cache_read_input_tokens=0,
        cache_write_input_tokens=1800,
    ),
)


def build_input(form) -> Input:
    r = FormReader(form)
    job_posting = r.text("job_posting", "Job posting", required=True)
    cv = r.text("cv", "Current CV", required=True)
    job_title = r.text("job_title", "Role title")
    job_company = r.text("job_company", "Company")
    tone = r.text("tone", "Tone")
    target_length = r.text("target_length", "Target length")
    region = r.text("region", "Region")
    emphasis = [Emphasis(point=point) for point in r.lines("emphasis")]
    background = r.text("background_documents", "Background notes")
    r.done()
    return Input(
        job_posting=job_posting,
        cv=cv,
        job_title=job_title,
        job_company=job_company,
        tone=tone,
        target_length=target_length,
        region=region,
        emphasis=emphasis,
        background_documents=[background] if background else [],
    )


def sections(output: Output) -> list[Section]:
    return [
        Section("Tailored CV", output.tailored_cv),
        Section("What it targeted", output.tailoring_note),
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
    slug="cv-writer",
    title="CV Writer",
    summary="A CV rewritten and reordered to target one job posting, plus a note on what it targeted.",
    fields=FIELDS,
    example_form=EXAMPLE_FORM,
    example_output=EXAMPLE_OUTPUT,
    build_input=build_input,
    run=run,
    sections=sections,
    run_meta=run_meta,
)
