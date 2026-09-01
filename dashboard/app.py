"""The FastAPI app: login, an index of pages, and two generic routes
(`GET`/`POST /p/{slug}`) that drive every capability page from its `Page`
spec. Adding a capability is adding a `Page` — never a route here.

The `/documents` and `/jobs` routes are the exception: app-native areas for
the dashboard's own stores (CLAUDE.md rule 6), not tied to any capability.
See `docs/BACKGROUND_DOCUMENTS.md` and `docs/JOB_POSTS.md`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import warnings
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from dashboard import _auth, _documents, _drafts, _job_analysis, _jobs, _targeted_edit
from dashboard._auth import is_authed
from dashboard._render import to_html
from dashboard.pages import PAGES_BY_SLUG
from dashboard.pages._spec import FormError, Page, RunMeta

_HERE = Path(__file__).resolve().parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"

_log = logging.getLogger("dashboard")

# A `slow=True` page streams its result: flush a holding view now, then a
# keepalive comment every few seconds until `run()` returns. Anything well
# under a hosting proxy's response timeout (Render's is ~100s) works.
_KEEPALIVE_SECONDS = 15


def _resolve_span(
    current: str, selection: str, span_start: int, span_len: int
) -> tuple[int, int] | None:
    """Where `selection` sits in `current`, as (start, len).

    The offsets the browser computed are trusted when they still line up.
    If they don't — a `<pre>` can normalise newlines, and the text may
    have shifted — fall back to locating the selection text itself, but
    only when it occurs exactly once (otherwise it's genuinely
    ambiguous / stale). Returns None when it can't be placed.
    """
    if selection and current[span_start : span_start + span_len] == selection:
        return span_start, span_len
    if selection:
        first = current.find(selection)
        if first != -1 and current.find(selection, first + 1) == -1:
            return first, len(selection)
    return None


def _asset_version() -> str:
    """Short hash of the static assets, appended as `?v=` to their URLs so
    a browser fetches the new file after a deploy instead of a stale cache."""
    h = hashlib.sha1()
    for name in ("app.css", "draft-edit.js"):
        try:
            h.update((_STATIC / name).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:8]


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


def create_app(
    *,
    auth_disabled: bool = False,
    stub_runs: bool = False,
    as_user: str = "test-user",
) -> FastAPI:
    app = FastAPI(title="Automation Dashboard")
    app.state.auth_disabled = auth_disabled
    # Who every request is from while `auth_disabled` — the synthetic id the
    # app's own stores scope by. Tests set it to check cross-user isolation.
    app.state.as_user = as_user
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
    templates.env.globals["asset_v"] = _asset_version()

    def render(name: str, request: Request, /, status_code: int = 200, **ctx):
        # Every page's topbar shows who is signed in — inject it once here
        # rather than in each handler. `_streamed_result` bypasses this and
        # passes `user_email` explicitly.
        ctx.setdefault(
            "user_email", u.email if (u := _auth.current_user(request)) else None
        )
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
        return render("login.html", request, next=next, email="", error=None)

    @app.post("/login", response_class=HTMLResponse)
    async def login_submit(request: Request):
        form = await request.form()
        next_url = str(form.get("next") or "/")
        email = str(form.get("email") or "").strip()
        password = str(form.get("password") or "")
        # Supabase Auth is a network call; keep it off the event loop.
        user = await run_in_threadpool(_auth.sign_in, email, password)
        if user is not None:
            request.session["user"] = {"id": user.id, "email": user.email}
            return RedirectResponse(next_url, status_code=303)
        return render(
            "login.html", request, status_code=401,
            next=next_url, email=email, error="Wrong email or password.",
        )

    @app.get("/logout")
    def logout(request: Request):
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    # --- pages -----------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        return render("index.html", request)

    async def _doc_choices(page: Page, user_id: str) -> list:
        if not _wants_documents(page):
            return []
        return await run_in_threadpool(_documents.list_documents, user_id)

    async def _job_choices(page: Page, user_id: str) -> list:
        if not _wants_jobs(page):
            return []
        return await run_in_threadpool(_jobs.list_job_posts, user_id)

    def _result_page(request: Request, page: Page, output: object) -> Response:
        meta = page.run_meta(output) if page.run_meta else None
        return render(
            "result.html", request,
            page=page, sections=page.sections(output), meta=meta,
        )

    def _streamed_result(request: Request, page: Page, data: object) -> StreamingResponse:
        """The result of a `slow=True` page, streamed.

        Flush the holding view straight away, then — while `run()` works in
        a worker thread — trickle out progress: a `window.__progress(...)`
        script per update for a `progress=True` page (bridged from the
        thread via `loop.call_soon_threadsafe`), or a bare keepalive
        comment otherwise. Finish with the real result markup plus a
        script that swaps it in. The first byte lands in well under a
        second, so a hosting proxy's time-to-first-byte / idle timeout
        can't kill a call that takes minutes. Headers are already sent by
        the time `run()` could fail, so a failure is rendered into the
        body, not as a 5xx.
        """
        tpl = templates.get_template
        # These three render outside `render()`, so the topbar's signed-in
        # email has to be passed in by hand.
        user_email = u.email if (u := _auth.current_user(request)) else None

        async def body():
            yield tpl("_running_open.html").render(page=page, user_email=user_email)

            loop = asyncio.get_running_loop()
            updates: asyncio.Queue[int] = asyncio.Queue()

            def on_progress(p: object) -> None:  # called from the worker thread
                loop.call_soon_threadsafe(updates.put_nowait, getattr(p, "words", 0))

            def call() -> object:
                if page.progress:
                    return page.run(data, on_progress=on_progress)
                return page.run(data)

            task = asyncio.ensure_future(run_in_threadpool(call))

            while not task.done():
                getter = asyncio.ensure_future(updates.get())
                done, _ = await asyncio.wait(
                    {getter, task}, timeout=_KEEPALIVE_SECONDS,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if getter in done:
                    words = getter.result()
                    while not updates.empty():  # coalesce a backlog, emit the latest
                        words = updates.get_nowait()
                    yield f"<script>window.__progress&&window.__progress({words})</script>\n"
                else:
                    getter.cancel()
                    if task not in done:
                        yield "<!-- working -->\n"

            try:
                output = task.result()
            except Exception as exc:  # noqa: BLE001 - any run() failure, shown in the body
                _log.exception("slow page %s: run() failed", page.slug)
                yield tpl("_running_error.html").render(
                    page=page, error=type(exc).__name__, user_email=user_email,
                )
                return
            meta = page.run_meta(output) if page.run_meta else None
            yield tpl("_running_close.html").render(
                page=page, sections=page.sections(output), meta=meta,
                user_email=user_email,
            )

        return StreamingResponse(
            body(),
            media_type="text/html; charset=utf-8",
            # ask intermediate proxies not to buffer the trickle
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/p/{slug}", response_class=HTMLResponse)
    async def page_form(request: Request, slug: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)  # never None past guard()
        page = PAGES_BY_SLUG.get(slug)
        if page is None:
            raise HTTPException(status_code=404)
        prefill = dict(page.example_form) if request.query_params.get("example") else {}
        return render(
            "page.html", request,
            page=page, values=prefill, errors={},
            documents=await _doc_choices(page, uid), jobs=await _job_choices(page, uid),
        )

    @app.post("/p/{slug}", response_class=HTMLResponse)
    async def page_submit(request: Request, slug: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)  # never None past guard()
        page = PAGES_BY_SLUG.get(slug)
        if page is None:
            raise HTTPException(status_code=404)
        form = _form_values(await request.form(), page)
        try:
            # `build_input` may hit the Background documents store to resolve a
            # picked id — run it off the event loop like `run()` itself. It
            # takes `uid` because those stores are per-user; the capability's
            # own `Input` never sees it.
            data = await run_in_threadpool(page.build_input, form, uid)
        except FormError as exc:
            return render(
                "page.html", request, status_code=422,
                page=page, values=form, errors=exc.errors,
                documents=await _doc_choices(page, uid), jobs=await _job_choices(page, uid),
            )
        if app.state.stub_runs:
            return _result_page(request, page, page.example_output)  # no capability call
        if page.slow:
            # A minutes-long `run()` would blow a hosting proxy's response
            # timeout before the first byte. Stream instead (see below).
            return _streamed_result(request, page, data)
        # `run()` is synchronous and can take 30–60s (LLM call). Offload it
        # to a worker thread so the event loop stays free to answer other
        # requests — including the platform health check.
        output = await run_in_threadpool(page.run, data)
        return _result_page(request, page, output)

    # --- background documents -------------------------------------------
    # The app's own store (CLAUDE.md rule 6), not a capability. Notes here
    # feed the writer pages' `background_documents` input via a checklist.

    @app.get("/documents", response_class=HTMLResponse)
    async def documents_list(request: Request):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        docs = await run_in_threadpool(_documents.list_documents, uid)
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
        uid = _auth.current_user_id(request)
        await run_in_threadpool(_documents.create_document, title, body, uid)
        return RedirectResponse("/documents", status_code=303)

    @app.get("/documents/{doc_id}", response_class=HTMLResponse)
    async def document_edit(request: Request, doc_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        doc = await run_in_threadpool(_documents.get_document, doc_id, uid)
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
        uid = _auth.current_user_id(request)
        form = await request.form()
        title = str(form.get("title") or "").strip()
        body = str(form.get("body") or "").strip()
        if not title:
            doc = await run_in_threadpool(_documents.get_document, doc_id, uid)
            return render(
                "document_form.html", request, status_code=422,
                doc=doc, values={"title": title, "body": body},
                errors={"title": "Title is required."},
            )
        updated = await run_in_threadpool(
            _documents.update_document, doc_id, title, body, uid
        )
        if updated is None:
            raise HTTPException(status_code=404)
        return RedirectResponse("/documents", status_code=303)

    @app.post("/documents/{doc_id}/delete", response_class=HTMLResponse)
    async def document_delete(request: Request, doc_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        await run_in_threadpool(_documents.delete_document, doc_id, uid)
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
        uid = _auth.current_user_id(request)
        jobs = await run_in_threadpool(_jobs.list_job_posts, uid)
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
        uid = _auth.current_user_id(request)
        job = await run_in_threadpool(_jobs.create_job_post, title, posting, uid)
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        job = await run_in_threadpool(_jobs.get_job_post, job_id, uid)
        if job is None:
            raise HTTPException(status_code=404)
        return render(
            "job_detail.html", request,
            job=job, values={}, errors={}, summary=None, meta=None,
            edit=request.query_params.get("edit") is not None,
        )

    @app.post("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_save(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        form = await request.form()
        title = str(form.get("title") or "").strip()
        posting = str(form.get("posting") or "").strip()
        emphasis = str(form.get("emphasis") or "")
        if not title or not posting:
            job = await run_in_threadpool(_jobs.get_job_post, job_id, uid)
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
                errors=errors, summary=None, meta=None, edit=True,
            )
        updated = await run_in_threadpool(
            lambda: _jobs.update_job_post(
                job_id, uid, title=title, posting=posting, emphasis=emphasis
            )
        )
        if updated is None:
            raise HTTPException(status_code=404)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/analyse", response_class=HTMLResponse)
    async def job_analyse(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        job = await run_in_threadpool(_jobs.get_job_post, job_id, uid)
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
                job=job, values={}, errors={}, summary=None, meta=None, edit=False,
                notice="The analysis came back empty — nothing was changed. Try again.",
            )
        text = _job_analysis.requirements_to_emphasis_text(analysis)
        updated = await run_in_threadpool(
            lambda: _jobs.update_job_post(job_id, uid, emphasis=text)
        )
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
            edit=False,
        )

    @app.post("/jobs/{job_id}/delete", response_class=HTMLResponse)
    async def job_delete(request: Request, job_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        await run_in_threadpool(_jobs.delete_job_post, job_id, uid)
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
        uid = _auth.current_user_id(request)
        draft = await run_in_threadpool(
            _drafts.create_or_get_draft, page_slug, section, text, uid
        )
        return RedirectResponse(f"/drafts/{draft.id}", status_code=303)

    @app.get("/drafts/{draft_id}", response_class=HTMLResponse)
    async def draft_edit(request: Request, draft_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        draft = await run_in_threadpool(_drafts.get_draft, draft_id, uid)
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
        uid = _auth.current_user_id(request)
        draft = await run_in_threadpool(_drafts.get_draft, draft_id, uid)
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
        span = _resolve_span(draft.current, selection, span_start, span_len)
        if span is None:
            return JSONResponse(
                {"error": "The selected text is no longer in the draft — reselect and try again."},
                status_code=409,
            )
        span_start, span_len = span

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
        uid = _auth.current_user_id(request)
        draft = await run_in_threadpool(_drafts.get_draft, draft_id, uid)
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
        span = _resolve_span(draft.current, selection, span_start, span_len)
        if span is None:
            return JSONResponse(
                {"error": "The selected text is no longer in the draft — reselect and try again."},
                status_code=409,
            )
        span_start, span_len = span
        updated = await run_in_threadpool(
            lambda: _drafts.record_revision(
                draft_id,
                uid,
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
        uid = _auth.current_user_id(request)
        updated = await run_in_threadpool(_drafts.undo_last, draft_id, uid)
        if updated is None:
            raise HTTPException(status_code=404)
        return JSONResponse(_draft_state(updated))

    @app.get("/drafts/{draft_id}/download")
    async def draft_download(request: Request, draft_id: str):
        if (redirect := guard(request)) is not None:
            return redirect
        uid = _auth.current_user_id(request)
        draft = await run_in_threadpool(_drafts.get_draft, draft_id, uid)
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
