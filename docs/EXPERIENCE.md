# The experience layer, in prose

## What this app is

One web app. Every capability module gets one page. The page's form is
built from the capability's `Input`; the results view is its `Output`.
The app fills in the job-order form, calls `run()` once, and shows what
comes back. It is the reception desk, not a workshop.

It depends on capabilities exactly as an orchestrator does — pinned git
dependencies, `run()` called directly — and nothing depends on it.

## A page is a `Page`

`dashboard/pages/_spec.py` defines the whole page contract:

| Piece | What it is |
|---|---|
| `slug` | the URL (`/p/<slug>`) |
| `title`, `summary` | shown on the index and the page |
| `fields` | one `Field` per capability `Input` argument — drives the generic form and the generic test |
| `example_form` | a valid demo submission; drives the generic test (a `?example=1` prefill still exists but is no longer linked from the page) |
| `example_output` | a canned `Output`; lets tests run the page offline |
| `build_input(form)` | turn the submitted form dict into the capability's `Input` (raise `FormError` for bad input) |
| `run(input)` | the capability's `run` — the *only* call into it |
| `sections(output)` | turn the `Output` into `Section(heading, markdown)` blocks |
| `run_meta(output)` | *optional.* Map the `Output` to a `RunMeta` (cost + token counts) for the result-page cost footer. Leave unset if the capability reports no cost. |

A `Field` has a `name` (must match the `Input` argument), a `label`, a
`widget` (`text` / `textarea` / `number` / `lines` / `checklist` /
`picker` / `doc_picker`), `required`, and `help` text. `lines` is a
textarea where each non-blank line becomes one list item — use it for
`list[str]` inputs. `checklist` renders one checkbox per saved document
and submits a list of ids; `doc_picker` is a `<select>` of saved
documents submitting one id (`picker` is the same over saved Job posts).
Read a checklist with `FormReader.multi(name)` and a picker with
`FormReader.text(name)`, then resolve the ids through
`dashboard._documents` / `dashboard._jobs` (see
`docs/BACKGROUND_DOCUMENTS.md`, `docs/JOB_POSTS.md`). Those `name`s are
app-storage keys — the fields whose names deliberately don't match an
`Input` argument; `build_input` folds the resolved text into the real
contract field.

`FormReader` (also in `_spec.py`) is a small helper for `build_input`: it
reads fields, collects every problem, and raises one `FormError` with all
of them so the form re-renders with each message next to its field.

## Run cost — the `run_meta` hook

A capability whose `Output` carries a cost (an LLM spend estimate plus
token counts) can surface it on the result page. Give the page a
`run_meta(output) -> RunMeta` that maps those fields across:

```python
from cover_letter_writer import Cost   # exported shape
from dashboard.pages._spec import RunMeta

CAPABILITY, CAPABILITY_VERSION = "cover-letter-writer", "v0.10.0"

def run_meta(out) -> RunMeta:
    c = out.cost
    return RunMeta(
        capability=CAPABILITY, capability_version=CAPABILITY_VERSION,
        cost_usd=c.usd, input_tokens=c.input_tokens, output_tokens=c.output_tokens,
        cache_read_input_tokens=c.cache_read_input_tokens,
        cache_write_input_tokens=c.cache_write_input_tokens,
    )
```

Wire it into `PAGE(..., run_meta=run_meta)`. The result template then
renders a small footer: `$0.0123 est.` plus a token caption and the
capability name + pinned tag. `example_output` must include a `cost` so
stub mode and the generic tests can render the footer offline.

`RunMeta` is a *usage* record, not a content archive — numbers plus which
capability (and version) produced them. It is the shape a later usage
store writes per run, so spend can be totalled across runs and, one day,
capped. Keep the `CAPABILITY_VERSION` constant in step with the pin in
`pyproject.toml`.

## Adding a page

### 1. Pin the capability

```
uv add "cover-letter-writer @ git+https://github.com/onlinemoose/cover-letter-writer.git@v0.9.0"
```

For local development against a capability checked out as a sibling
folder, override the pin in `pyproject.toml`:

```toml
[tool.uv.sources]
cover-letter-writer = { path = "../cover-letter-writer", editable = true }
```

Keep the `git` pin as the real dependency; `[tool.uv.sources]` is a
local-only override and does not travel to a deployment.

### 2. Write the page

Copy `dashboard/pages/example.py` to `dashboard/pages/cover_letter_writer.py`:

```python
from cover_letter_writer import Emphasis, Input, Output, run
from dashboard.pages._spec import Field, FormReader, Page, Section

FIELDS = (
    Field("job_posting", "Job posting", widget="textarea", required=True,
          help="The full posting text."),
    Field("cv", "CV", widget="textarea", required=True,
          help="Plain text. Convert PDFs first."),
    Field("tone", "Tone", widget="text",
          help="Optional. e.g. warm, formal, direct."),
    Field("emphasis", "Points to emphasise", widget="lines",
          help="Optional. One per line, most important first."),
)

EXAMPLE_FORM = {"job_posting": "...", "cv": "...", "tone": "measured", "emphasis": "lead with the payments work"}

def build_input(form):
    r = FormReader(form)
    job_posting = r.text("job_posting", "Job posting", required=True)
    cv = r.text("cv", "CV", required=True)
    tone = r.text("tone", "Tone")
    emphasis = [Emphasis(point=p) for p in r.lines("emphasis")]
    r.done()
    return Input(job_posting=job_posting, cv=cv, tone=tone, emphasis=emphasis)

def sections(out: Output):
    return [Section("Cover letter", out.cover_letter),
            Section("What it targeted", out.targeting_note)]

EXAMPLE_OUTPUT = Output(cover_letter="_(example letter)_", targeting_note="_(example note)_")

PAGE = Page(
    slug="cover-letter-writer",
    title="Cover Letter Writer",
    summary="A tailored cover letter from a job posting and a CV.",
    fields=FIELDS, example_form=EXAMPLE_FORM, example_output=EXAMPLE_OUTPUT,
    build_input=build_input, run=run, sections=sections,
)
```

Only map inputs the contract actually has. Optional contract inputs are
optional fields; leave out any you don't want to expose yet.

### 3. Register it

`dashboard/pages/__init__.py`:

```python
from dashboard.pages import cover_letter_writer, example

PAGES = [example.PAGE, cover_letter_writer.PAGE]
```

### 4. Test

```
uv run pytest
```

The generic suite in `tests/test_pages.py` now exercises the new page:
the form renders every field, `example_form` submits, `build_input`
produces the capability's `Input`, `run()` is called (stubbed), and every
`sections()` heading shows in the result. Add page-specific tests only
for `build_input` logic that's worth pinning (parsing, defaults).

### 5. Log it

Add a `docs/PROGRESS.md` entry: which capability, pinned at which tag.

## Stub mode — the UI without the API

`DASHBOARD_STUB_RUNS=1` (or `create_app(stub_runs=True)`) makes every
`POST /p/{slug}` skip `page.run()` and render that page's
`example_output` instead. No API key, no cost, no 30–60s wait — the whole
app is clickable for UI work and demos. A banner shows while it's on.

It exercises everything the experience layer owns (the form,
`build_input`, `sections()`, the result template) but *not* the
capability call — that has its own tests. `tests/test_pages.py` asserts
stub mode renders `example_output` without calling `run()`.

## App-owned storage

The dashboard holds no domain data, but it may keep its *own* — saved
notes, run history, accounts (CLAUDE.md rule 6). The first of these is the
**Background documents** area: `dashboard/_documents.py` (a Supabase
table) plus the `/documents` routes in `app.py`. These routes are
app-native — not a capability page, exempt in `test_guardrails.py`'s
`ALLOWED_ROUTES` — and that's the pattern any later store (a `/usage`
page, say) follows. Full write-up: `docs/BACKGROUND_DOCUMENTS.md`.

The **Job posts** area (`dashboard/_jobs.py`, `/jobs*`,
`docs/JOB_POSTS.md`) and the **Working drafts** area (`dashboard/_drafts.py`,
`/drafts*`, `docs/DRAFTS.md`) follow the same pattern. Working drafts is
also where the app owns a little real logic: a result section can be
opened as an editable draft, and `apply_revision()` splices an accepted
span revision into the stored text (undo is replay from the immutable
`original`). The revision itself is a capability call at an allowed seam —
`targeted-editor`, invoked from the `/drafts/{id}/revise` handler.

## Chaining capabilities

When a page needs two capabilities — e.g. extract text from an upload,
then write a cover letter from it — call them in sequence inside
`build_input` / the handler, capability A's `Output` feeding capability
B's `Input`. That sequencing lives here (or in a Prefect flow), never
inside a capability. If the chain gets long or is reused, that's the
signal to move it into an orchestration project and have this page
trigger the flow instead.

A chain with a person in the middle stays here regardless of length. The
Job posts area (`docs/JOB_POSTS.md`) is one: `job-post-analyst` turns a
posting into a prioritised emphasis list, the user annotates each point,
then `cover-letter-writer` / `cv-writer` consume the result. Because a
human step sits between the two `run()`s it can't be a headless flow —
it's an app-owned store (`_jobs.py`) plus a `"picker"` field, not a
Prefect pipeline.

## Upgrading a capability

A capability releasing a new tag changes nothing here until you move the
pin: `uv add "<capability> @ …@vX.Y.Z"` (new tag), `uv lock`, check the
page still matches the contract, `uv run pytest`, `docs/PROGRESS.md`
entry. A bad upgrade is a one-line pin revert.

## Long calls

`run()` for an LLM-backed capability can take 30–60s. The POST is
synchronous — the browser waits, the page shows "this can take up to a
minute". The `run()` call is offloaded to a worker thread
(`run_in_threadpool`) so it doesn't block the event loop: other requests,
and the platform health check, keep being answered while a letter is
generating. Without that, a blocked event loop fails the health check and
the host restarts the instance mid-request (seen as 502s on the assets
right after the result page). A job queue (submit, poll, collect) is a
deliberate later addition, not part of this template.

### Slow pages

Some capabilities produce a long-form document from one LLM call and run
for *minutes*, not seconds (a full-length regional CV — a German
Lebenslauf — is the case that forced this). A plain synchronous POST
sends nothing until `run()` returns, so a hosting proxy that drops a
request with no response bytes for ~100s (Render does) kills it before
the result exists. Locally there's no such proxy, so it "works on my
machine".

Set `slow=True` on those pages' `Page`. The submit route then returns a
`StreamingResponse` that:

1. flushes a holding view (`templates/_running_open.html`) in the first
   second — a spinner, an elapsed clock, and "keep this tab open";
2. while `run()` works in a worker thread, trickles bytes so the
   connection never idles out: a bare HTML-comment keepalive every
   `_KEEPALIVE_SECONDS`, or — for a `progress=True` page — a
   `window.__progress(words)` script per update (see below);
3. streams the real result panel plus a one-line script that removes the
   placeholder (`_running_close.html`), or an in-body error notice if
   `run()` raised (`_running_error.html` — the `200` headers are already
   sent, so a failure can't be a 5xx here).

`_result_panel.html` is the shared partial: `result.html` includes it for
quick pages, the streamed close reuses it verbatim. Stub mode ignores
`slow` (there's no call to wait on). This is still not a job queue —
it holds the one request open, cleanly, for the few minutes it needs.

**Live progress (`progress=True`).** When the page's capability `run()`
accepts a keyword-only `on_progress` callback (cv-writer ≥ v0.5.0,
cover-letter-writer ≥ v0.13.0), also set `progress=True`. The submit
route then passes a callback that bridges the worker thread to the
response stream — `loop.call_soon_threadsafe(queue.put_nowait, …)` — and
emits a `<script>window.__progress(<words>)</script>` chunk per update.
The holding view's inline script shows `Thinking through the brief… 0:18`
until the first word arrives, then `Writing… 640 words · 1:12` off its
own 1-second clock (the server sends only the word count). No percentage:
there's no honest denominator. If the capability has no `on_progress`,
leave `progress` unset and the page falls back to the bare keepalive.
