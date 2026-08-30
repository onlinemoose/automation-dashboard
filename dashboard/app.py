"""The FastAPI app: login, an index of pages, and two generic routes
(`GET`/`POST /p/{slug}`) that drive every capability page from its `Page`
spec. Adding a capability is adding a `Page` — never a route here.
"""

from __future__ import annotations

import os
import secrets
import warnings
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware

from dashboard._auth import is_authed, password_hash, verify_password
from dashboard._render import to_html
from dashboard.pages import PAGES, PAGES_BY_SLUG
from dashboard.pages._spec import FormError

_HERE = Path(__file__).resolve().parent
_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


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

    @app.get("/p/{slug}", response_class=HTMLResponse)
    def page_form(request: Request, slug: str):
        if (redirect := guard(request)) is not None:
            return redirect
        page = PAGES_BY_SLUG.get(slug)
        if page is None:
            raise HTTPException(status_code=404)
        prefill = dict(page.example_form) if request.query_params.get("example") else {}
        return render("page.html", request, page=page, values=prefill, errors={})

    @app.post("/p/{slug}", response_class=HTMLResponse)
    async def page_submit(request: Request, slug: str):
        if (redirect := guard(request)) is not None:
            return redirect
        page = PAGES_BY_SLUG.get(slug)
        if page is None:
            raise HTTPException(status_code=404)
        form = {k: str(v) for k, v in (await request.form()).items()}
        try:
            data = page.build_input(form)
        except FormError as exc:
            return render(
                "page.html", request, status_code=422,
                page=page, values=form, errors=exc.errors,
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

    return app


app = create_app()
