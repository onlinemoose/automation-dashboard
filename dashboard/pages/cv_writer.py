"""Page for the `cv-writer` capability (pinned at v0.5.0).

Maps the capability's contract to a form. Optional contract inputs that
aren't exposed yet: `previous_draft` / `previous_feedback` (the revision
loop needs the prior output carried back — a later addition) and the
operator-config inputs `house_style` / `expert_guidance`.
"""

from __future__ import annotations

from pathlib import Path

from cv_writer import Cost, Emphasis, Input, Output, run

from dashboard import _documents, _jobs
from dashboard._job_analysis import parse_annotated_emphasis
from dashboard.pages._spec import Field, FormReader, Page, RunMeta, Section

# The pinned tag, kept in step with `[tool.uv.sources]` in pyproject.toml.
# Stamped onto every RunMeta so usage records say which build produced them.
CAPABILITY = "cv-writer"
CAPABILITY_VERSION = "v0.5.0"

# Demo inputs, vendored into this repo (a neutralised posting + a matching
# fictional CV). They belong to the page, not the capability — the
# capability's own examples aren't part of its contract and aren't in the
# installed package. Swap `cv.md` for your own CV to make "Load example"
# produce a CV you'd actually use.
_EXAMPLES = Path(__file__).parent / "_examples" / "cv_writer"

FIELDS = (
    Field(
        "job_post_id",
        "Load a saved job post",
        widget="picker",
        help="Optional. Pick one to fill the job posting and emphasis from your "
        "analysed, annotated list under Job posts. Overrides the two boxes below.",
    ),
    Field(
        "job_posting",
        "Job posting",
        widget="textarea",
        help="The full posting text — title, company, responsibilities, requirements. "
        "Required unless you load a saved job post above.",
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
        help="Optional. One point per line, most important first. A saved job "
        'post fills this with an analysed list — "> " lines quote the posting, '
        '"- " lines are your own notes.',
    ),
    Field(
        "background_document_ids",
        "Saved documents",
        widget="checklist",
        help="Optional. Tick any saved notes to include as background context for "
        "this run. Manage them under Documents.",
    ),
    Field(
        "background_documents",
        "Background notes",
        widget="textarea",
        help="Optional. A one-off note for this run only — portfolio notes, project "
        "write-ups, a bio, older roles left off the CV, company context. Treated "
        "as one document.",
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


def build_input(form, user_id: str) -> Input:
    r = FormReader(form)
    # `job_post_id` is a key into the app's own Job posts store (like
    # `background_document_ids`), not a contract argument. When set it fills
    # `job_posting` and `emphasis` from the analysed, annotated posting.
    # Those stores are per-user, hence `user_id` — it never reaches `Input`.
    job_post_id = r.text("job_post_id", "Saved job post")
    job_post = _jobs.get_job_post(job_post_id, user_id) if job_post_id else None
    if job_post is not None:
        job_posting = job_post.posting
        emphasis_source = job_post.emphasis
    else:
        job_posting = r.text("job_posting", "Job posting", required=True)
        emphasis_source = form.get("emphasis") or ""
    cv = r.text("cv", "Current CV", required=True)
    job_title = r.text("job_title", "Role title")
    job_company = r.text("job_company", "Company")
    tone = r.text("tone", "Tone")
    target_length = r.text("target_length", "Target length")
    region = r.text("region", "Region")
    emphasis = [
        Emphasis(point=p.point, quote=p.quote)
        for p in parse_annotated_emphasis(emphasis_source)
    ]
    # `background_document_ids` are keys into the app's own Background documents
    # store; resolve them to text and fold into the contract's `background_documents`.
    saved = _documents.get_documents(r.multi("background_document_ids"), user_id)
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
        background_documents=[
            *(doc.body for doc in saved),
            *([background] if background else []),
        ],
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
    # A tailored CV is a long-form document from one LLM call; a full-length
    # regional CV (e.g. a German Lebenslauf) can run for minutes.
    slow=True,
    # cv-writer's run() takes an on_progress callback (v0.5.0+) — the
    # holding view shows a live word count.
    progress=True,
)
