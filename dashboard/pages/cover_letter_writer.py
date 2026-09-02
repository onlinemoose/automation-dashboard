"""Page for the `cover-letter-writer` capability (pinned at v0.13.0).

Maps the capability's contract to a form. Optional contract inputs that
aren't exposed yet: `previous_draft` / `previous_feedback` (the revision
loop needs the prior output carried back — a later addition) and the
operator-config inputs `house_style` / `expert_guidance`.
"""

from __future__ import annotations

from pathlib import Path

from cover_letter_writer import Cost, Emphasis, Input, Output, run

from dashboard import _documents, _jobs
from dashboard._job_analysis import parse_annotated_emphasis
from dashboard.pages._spec import Field, FormError, FormReader, Page, RunMeta, Section

# The pinned tag, kept in step with `[tool.uv.sources]` in pyproject.toml.
# Stamped onto every RunMeta so usage records say which build produced them.
CAPABILITY = "cover-letter-writer"
CAPABILITY_VERSION = "v0.13.0"

# Demo inputs, vendored into this repo (a neutralised, shortened real
# posting + a matching fictional CV). They belong to the page, not the
# capability — the capability's own examples aren't part of its contract
# and aren't in the installed package. Swap `cv.md` for your own CV to
# make "Load example" produce a letter you'd actually send.
_EXAMPLES = Path(__file__).parent / "_examples" / "cover_letter_writer"

FIELDS = (
    Field(
        # Not a picker any more: this page is always opened from a Job post
        # (`/p/cover-letter-writer?job_post_id=<id>`, the icons on /jobs), so
        # the id just rides along hidden. A bare visit redirects to /jobs.
        "job_post_id",
        "Job post",
        widget="hidden",
    ),
    Field(
        "cv_document_id",
        "Load a saved CV",
        widget="doc_picker",
        help="Pick your CV from the documents library. Paste it in once under "
        "Documents (plain text or Markdown), then reuse it here every run.",
    ),
    Field(
        "job_title",
        "Role title",
        widget="text",
        from_job_post="job_title",
        help="Optional. Only if it isn't obvious from the posting.",
    ),
    Field(
        "job_company",
        "Company",
        widget="text",
        from_job_post="company",
        help="Optional. Only if it isn't obvious from the posting.",
    ),
    Field(
        "tone",
        "Tone",
        widget="text",
        help="Optional. e.g. warm, formal, direct. Free text.",
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
        help="Optional. A one-off note for this run only — portfolio notes, a bio, "
        "answers to application questions, company context. Treated as one document.",
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
    # The job_posting and cv fields aren't rendered any more (a saved job
    # post and a saved CV document are the way in). These raw values are the
    # fallback build_input reads when nothing is picked — they keep the
    # generic page test runnable without a live store.
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
        # The job_posting and emphasis fields were removed — a picked job
        # post is the way in, and it carries both. Raw job_posting /
        # emphasis may still arrive from the example form or a direct API
        # post; otherwise a saved job post must be picked.
        job_posting = (form.get("job_posting") or "").strip()
        emphasis_source = form.get("emphasis") or ""
        if not job_posting:
            raise FormError({"job_post_id": "Load a saved job post."})
    # `cv_document_id` is an app storage key too — it resolves to the chosen
    # document's body. A raw `cv` may still arrive from the example form or
    # a direct API post; otherwise a saved CV must be picked.
    cv_document_id = r.text("cv_document_id", "Saved CV")
    cv_doc = _documents.get_document(cv_document_id, user_id) if cv_document_id else None
    if cv_doc is not None:
        cv = cv_doc.body
    else:
        cv = (form.get("cv") or "").strip()
        if not cv:
            raise FormError({"cv_document_id": "Load a saved CV."})
    job_title = r.text("job_title", "Role title")
    job_company = r.text("job_company", "Company")
    tone = r.text("tone", "Tone")
    emphasis = [
        Emphasis(point=p.point, quote=p.quote)
        for p in parse_annotated_emphasis(emphasis_source)
    ]
    # `background_document_ids` are keys into the app's own Background documents
    # store; resolve them to text and fold into the contract's `background_documents`.
    saved = _documents.get_documents(r.multi("background_document_ids"), user_id)
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
        background_documents=[
            *(doc.body for doc in saved),
            *([background] if background else []),
        ],
        max_words=max_words,
        salary_expectation=salary_expectation,
        availability=availability,
    )


def sections(output: Output) -> list[Section]:
    return [
        Section("Cover letter", output.cover_letter),
        # A read-only note on what the letter aimed at — not something you
        # revise span by span, so no "Edit draft".
        Section("What it targeted", output.targeting_note, editable=False),
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
    # One LLM call drafting a full letter plus a targeting note; long
    # postings and CVs push this past a minute.
    slow=True,
    # cover-letter-writer's run() takes an on_progress callback (v0.13.0+)
    # — the holding view shows a live word count.
    progress=True,
    # A finished letter is saved against the job post it was written for
    # (the `cover_letter` column on `job_posts`); re-opening this page for
    # that post shows it instead of a blank form.
    saved_result_slot="cover_letter",
)
