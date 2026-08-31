"""The FastAPI app: login, an index of pages, and two generic routes
(`GET`/`POST /p/{slug}`) that drive every capability page from its `Page`
spec. Adding a capability is adding a `Page` — never a route here.

The `/documents` and `/jobs` routes are the exception: app-native areas for
the dashboard's own stores (CLAUDE.md rule 6), not tied to any capability.
See `docs/BACKGROUND_DOCUMENTS.md` and `docs/JOB_POSTS.md`.
"""

from __future__ import annotations

import json
import os
import secrets
import warnings
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from dashboard import _documents, _drafts, _job_analysis, _jobs, _targeted_edit
from dashboard._auth import is_authed, password_hash, verify_password
from dashboard._render import to_html
from dashboard.pages import PAGES, PAGES_BY_SLUG
from dashboard.pages._spec import FormError, Page, RunMeta

_HERE = Path(__file__).resolve().parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


def _wants_documents(page: Page) -> bool:
    return any(f.widget == "checklist" for f in page.fields)


def _wants_jobs(page: Page) -> bool:
    return any(f.widget == "picker" for f in page.fields)


def _form_values(raw, page: Page) -> dict[str, object]:
    """The submitted form as the templates and `build_input` expect it:
    "checklist" fields become a list of values, everything else a string."""
    checklist = {f.name for f in page.fields if f.widget == "checklist"}
    values: dict[str, object] = {}
    for key in set(raw.keys()):
        if key in checklist:
            values[key] = [v for v in raw.getlist(key) if v]
        else:
            values[key] = str(raw.get(key))
    return values


def _session_secret() -> str:
    value = os.environ.get("SESSION_SECRET")
    if not value:
        warnings.warn(
            "SESSION_SECRET is not set — using an ephemeral key; logins will "
            "not survive a restart. Set one in .env for anything real.",
            stacklevel=2,
        )
        value = secrets.token_urlsafe(32)
    return value


def create_app(*, auth_disabled: bool = False, stub_runs: bool = False) -> FastAPI:
    app = FastAPI(title="Automation Dashboard")
    app.state.auth_disabled = auth_disabled
    # Stub mode: skip the capability call, render its `example_output`. Lets
    # you click through the whole app with no API key, no cost, no wait.
    app.state.stub_runs = stub_runs or os.environ.get("DASHBOARD_STUB_RUNS", "0") == "1"
    app.add_middleware(
        SessionMiddleware,
        secret_key=_session_secret(),
        same_site="lax",
        https_only=os.environ.get("DASHBOARD_HTTPS", "0") == "1",
    )
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")

    templates = Jinja2Templates(directory=str(_TEMPLATES))
    templates.env.filters["markdown"] = to_html
    templates.env.filters["thousands"] = lambda n: f"{int(n):,}"
    templates.env.filters["usd4"] = lambda n: f"${float(n):.4f}"
    templates.env.globals["stub_runs"] = app.state.stub_runs

    def render(name: str, request: Request, /, status_code: int = 200, **ctx):
        return templates.TemplateResponse(request, name, ctx, status_code=status_code)

    def guard(request: Request) -> RedirectResponse | None:
        if is_authed(request):
            return None
        return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)

    # --- health & auth -----------------------------------------------------

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    @app.get("/login", response_class=HTMLResponse)
    def login_form(request: Request, next: str = "/"):
        return render("login.html", request, next=next, error=None)

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(request: Request):
        form = await request.form()
        next_url = str(form.get("next") or "/")
        if password_hash() and verify_password(str(form.get("password") or ""), password_hash()):
            request.session["authed"] = True
            return RedirectResponse(next_url, status_code=303)
        return render("login.html", request, status_code=401, next=next_url, error="Wrong password.")

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # --- pages -----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        return render("index.html", request, pages=PAGES)

    async def _doc_choices(page: Page) -> list:
        return await run_in_threadpool(_documents.list_documents) if _wants_documents(page) else []

    async def _job_choices(page: Page) -> list:
        return await run_in_threadpool(_jobs.list_job_posts) if _wants_jobs(page) else []

    @app.get("/p/{slug}", response_class=HTMLResponse)
    async def page_form(request: Request, slug: str):
        if (redirect := guard(request)) is not None:
            return redirect
        page = PAGES_BY_SLUG.get(slug)
        if page is None:
            raise HTTPException(status_code=404)
        prefill = dict(page.example_form) if request.query_params.get("example") else {}
        return render(
            "page.html", request,
            page=page, values=prefill, errors={},
            documents=await _doc_choices(page), jobs=await _job_choices(page),
        )

    @app.post("/p/{slug}", response_class=HTMLResponse)
    async def page_submit(request: Request, slug: str):
        if (redirect := guard(request)) is not None:
            return redirect
        page = PAGES_BY_SLUG.get(slug)
        if page is None:
            raise HTTPException(status_code=404)
        form = _form_values(await request.form(), page)
        try:
            # `build_input` may hit the Background documents store to resolve a
            # picked id — run it off the event loop like `run()` itself.
            data = await run_in_threadpool(page.build_input, form)
        except FormError as exc:
            return render(
                "page.html", request, status_code=422,
                page=page, values=form, errors=exc.errors,
                documents=await _doc_choices(page), jobs=await _job_choices(page),
            )
        if app.state.stub_runs:
            output = page.example_output  # stub mode: no capability call
        else:
            # `run()` is synchronous and can take 30–60s (LLM call). Offload it
            # to a worker thread so the event loop stays free to answer other
            # requests — including the platform health check.
            output = await run_in_threadpool(page.run, data)
        meta = page.run_meta(output) if page.run_meta else None
        return render(
            "result.html", request,
            page=page, sections=page.sections(output), meta=meta,
        )

    # --- background documents -------------------------------------------
    # The app's own store (CLAUDE.md rule 6), not a capability. Notes here
    # feed the writer pages' `background_documents` input via a checklist.

    @app.get("/documents", response_class=HTMLResponse)
    async def documents_list(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        docs = await run_in_threadpool(_documents.list_documents)
        return render("documents.html", request, documents=docs)

    @app.get("/documents/new", response_class=HTMLResponse)
    def document_new(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        return render("document_form.html", request, doc=None, values={}, errors={})

    @app.post("/documents/new", response_class=HTMLResponse)
    async def document_create(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        form = await request.form()
        title = str(form.get("title") or "").strip()
        body = str(form.get("body") or "").strip()
        if not title:
            return render(
                "document_form.html", request, status_code=422,
                doc=None, values={"title": title, "body": body},
                errors={"title": "Title is required."},
            )
        await run_in_threadpool(_documents.create_document, title, body)
        return RedirectResponse("/documents", status_code=303)

    @app.get("/documents/{doc_id}", response_class=HTMLResponse)
    async def document_edit(request: Request, doc_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        doc = await run_in_threadpool(_documents.get_document, doc_id)
        if doc is None:
            raise HTTPException(status_code=404)
        return render(
            "document_form.html", request,
            doc=doc, values={"title": doc.title, "body": doc.body}, errors={},
        )

    @app.post("/documents/{doc_id}", response_class=HTMLResponse)
    async def document_update(request: Request, doc_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        form = await request.form()
        title = str(form.get("title") or "").strip()
        body = str(form.get("body") or "").strip()
        if not title:
            doc = await run_in_threadpool(_documents.get_document, doc_id)
            return render(
                "document_form.html", request, status_code=422,
                doc=doc, values={"title": title, "body": body},
                errors={"title": "Title is required."},
            )
        updated = await run_in_threadpool(_documents.update_document, doc_id, title, body)
        if updated is None:
            raise HTTPException(status_code=404)
        return RedirectResponse("/documents", status_code=303)

    @app.post("/documents/{doc_id}/delete", response_class=HTMLResponse)
    async def document_delete(request: Request, doc_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        await run_in_threadpool(_documents.delete_document, doc_id)
        return RedirectResponse("/documents", status_code=303)

    # --- job posts -----------------------------------------------------
    # The app's own store (CLAUDE.md rule 6), not a capability. Add a
    # posting once, analyse it into a prioritised emphasis list, annotate
    # each point, then load it into the writer pages via a "picker" field.
    # See `docs/JOB_POSTS.md`.

    @app.get("/jobs", response_class=HTMLResponse)
    async def jobs_list(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        jobs = await run_in_threadpool(_jobs.list_job_posts)
        return render("jobs.html", request, jobs=jobs)

    @app.get("/jobs/new", response_class=HTMLResponse)
    def job_new(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        return render("job_form.html", request, values={}, errors={})

    @app.post("/jobs/new", response_class=HTMLResponse)
    async def job_create(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        form = await request.form()
        title = str(form.get("title") or "").strip()
        posting = str(form.get("posting") or "").strip()
        errors = {}
        if not title:
            errors["title"] = "Title is required."
        if not posting:
            errors["posting"] = "Paste the job posting."
        if errors:
            return render(
                "job_form.html", request, status_code=422,
                values={"title": title, "posting": posting}, errors=errors,
            )
        job = await run_in_threadpool(_jobs.create_job_post, title, posting)
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        job = await run_in_threadpool(_jobs.get_job_post, job_id)
        if job is None:
            raise HTTPException(status_code=404)
        return render(
            "job_detail.html", request,
            job=job, values={}, errors={}, summary=None, meta=None,
        )

    @app.post("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_save(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        form = await request.form()
        title = str(form.get("title") or "").strip()
        posting = str(form.get("posting") or "").strip()
        emphasis = str(form.get("emphasis") or "")
        if not title or not posting:
            job = await run_in_threadpool(_jobs.get_job_post, job_id)
            if job is None:
                raise HTTPException(status_code=404)
            errors = {}
            if not title:
                errors["title"] = "Title is required."
            if not posting:
                errors["posting"] = "The job posting can't be empty."
            return render(
                "job_detail.html", request, status_code=422,
                job=job, values={"title": title, "posting": posting, "emphasis": emphasis},
                errors=errors, summary=None, meta=None,
            )
        updated = await run_in_threadpool(
            _jobs.update_job_post, job_id,
            title=title, posting=posting, emphasis=emphasis,
        )
        if updated is None:
            raise HTTPException(status_code=404)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/analyse", response_class=HTMLResponse)
    async def job_analyse(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        job = await run_in_threadpool(_jobs.get_job_post, job_id)
        if job is None:
            raise HTTPException(status_code=404)
        analysis = await run_in_threadpool(_job_analysis.analyse, job.posting)
        if not analysis.requirements:
            # The capability returned nothing usable (e.g. a model reply its
            # normaliser couldn't recover). Leave the emphasis list alone —
            # overwriting it with a blank loses the user's annotations for
            # nothing — and say so instead of rendering an empty result.
            return render(
                "job_detail.html", request, status_code=502,
                job=job, values={}, errors={}, summary=None, meta=None,
                notice="The analysis came back empty — nothing was changed. Try again.",
            )
        text = _job_analysis.requirements_to_emphasis_text(analysis)
        updated = await run_in_threadpool(_jobs.update_job_post, job_id, emphasis=text)
        cost = analysis.cost
        meta = RunMeta(
            capability="job-analyst",
            capability_version=_job_analysis.capability_version(),
            cost_usd=float(cost.usd),
            input_tokens=cost.input_tokens,
            output_tokens=cost.output_tokens,
            cache_read_input_tokens=cost.cache_read_input_tokens,
            cache_write_input_tokens=cost.cache_write_input_tokens,
        )
        return render(
            "job_detail.html", request,
            job=updated, values={}, errors={}, summary=analysis.summary, meta=meta,
        )

    @app.post("/jobs/{job_id}/delete", response_class=HTMLResponse)
    async def job_delete(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        await run_in_threadpool(_jobs.delete_job_post, job_id)
        return RedirectResponse("/jobs", status_code=303)

    # --- working drafts ------------------------------------------------
    # The app's own store (CLAUDE.md rule 6), not a capability. A result
    # section can be opened as an editable draft; the user selects a span,
    # gives an instruction, and the `targeted-editor` capability revises
    # that span only. The splice, linear history, and undo-by-replay are
    # the app's own (`_drafts.py`). See `docs/DRAFTS.md`.

    def _draft_state(draft: _drafts.Draft) -> dict:
        return {
            "current": draft.current,
            "revision_count": len(draft.revisions),
            "can_undo": bool(draft.revisions),
        }

    @app.post("/drafts", response_class=HTMLResponse)
    async def draft_open(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        form = await request.form()
        page_slug = str(form.get("slug") or "").strip()
        section = str(form.get("section") or "").strip()
        text = str(form.get("text") or "")
        if not page_slug or not section or not text.strip():
            raise HTTPException(status_code=422, detail="slug, section and text are required")
        draft = await run_in_threadpool(
            _drafts.create_or_get_draft, page_slug, section, text
        )
        return RedirectResponse(f"/drafts/{draft.id}", status_code=303)

    @app.get("/drafts/{draft_id}", response_class=HTMLResponse)
    async def draft_edit(request: Request, draft_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        draft = await run_in_threadpool(_drafts.get_draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404)
        return render(
            "draft.html", request,
            draft=draft,
            capability=_targeted_edit.CAPABILITY,
            capability_version=_targeted_edit.capability_version(),
        )

    @app.post("/drafts/{draft_id}/revise")
    async def draft_revise(request: Request, draft_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        draft = await run_in_threadpool(_drafts.get_draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404)
        form = await request.form()
        selection = str(form.get("selection") or "")
        instruction = str(form.get("instruction") or "").strip()
        try:
            span_start = int(form.get("span_start"))
            span_len = int(form.get("span_len"))
        except (TypeError, ValueError):
            return JSONResponse({"error": "bad span offsets"}, status_code=422)
        if not instruction:
            return JSONResponse({"error": "An instruction is required."}, status_code=422)
        if draft.current[span_start:span_start + span_len] != selection:
            return JSONResponse(
                {"error": "The selection is out of date — reload and try again."},
                status_code=409,
            )

        if app.state.stub_runs:
            proposed = _targeted_edit.Revision(
                revised=f"[stubbed revision] {selection.strip()}",
                note="Stub mode — no capability call.",
                cost=_targeted_edit.Cost(),
            )
        else:
            try:
                proposed = await run_in_threadpool(
                    _targeted_edit.revise,
                    draft.current, selection, instruction,
                    kind=_targeted_edit.kind_for_section(draft.section),
                )
            except (ValueError, RuntimeError) as exc:
                return JSONResponse({"error": str(exc)}, status_code=422)

        return JSONResponse(
            {
                "revised": proposed.revised,
                "note": proposed.note,
                "cost": proposed.cost.to_dict(),
                "span_start": span_start,
                "span_len": span_len,
            }
        )

    @app.post("/drafts/{draft_id}/accept")
    async def draft_accept(request: Request, draft_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        draft = await run_in_threadpool(_drafts.get_draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404)
        form = await request.form()
        selection = str(form.get("selection") or "")
        revised = str(form.get("revised") or "")
        instruction = str(form.get("instruction") or "").strip()
        note = str(form.get("note") or "").strip()
        try:
            span_start = int(form.get("span_start"))
            span_len = int(form.get("span_len"))
        except (TypeError, ValueError):
            return JSONResponse({"error": "bad span offsets"}, status_code=422)
        try:
            cost = json.loads(str(form.get("cost") or "{}"))
            if not isinstance(cost, dict):
                cost = {}
        except ValueError:
            cost = {}
        if draft.current[span_start:span_start + span_len] != selection:
            return JSONResponse(
                {"error": "The selection is out of date — reload and try again."},
                status_code=409,
            )
        updated = await run_in_threadpool(
            lambda: _drafts.record_revision(
                draft_id,
                instruction=instruction,
                selection=selection,
                span_start=span_start,
                span_len=span_len,
                revised=revised,
                note=note,
                cost=cost,
            )
        )
        if updated is None:
            raise HTTPException(status_code=404)
        return JSONResponse(_draft_state(updated))

    @app.post("/drafts/{draft_id}/undo")
    async def draft_undo(request: Request, draft_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        updated = await run_in_threadpool(_drafts.undo_last, draft_id)
        if updated is None:
            raise HTTPException(status_code=404)
        return JSONResponse(_draft_state(updated))

    @app.get("/drafts/{draft_id}/download")
    async def draft_download(request: Request, draft_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        draft = await run_in_threadpool(_drafts.get_draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404)
        name = f"{draft.slug}-{draft.section}".strip("-") or "draft"
        return Response(
            content=draft.current,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
        )

    return app


app = create_app()
