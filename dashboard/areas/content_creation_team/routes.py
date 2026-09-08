"""The Content Creation Team area's routes — an `APIRouter` the shell
mounts (docs/AREAS.md). Everything under `/content*`:

- Content briefs CRUD (mirrors `/jobs*`): create/save a brief, list it.
- Run the content team from a brief — a streamed holding view (the run
  is ~4 min), the finished piece persisted onto the brief.
- "Send back to the content team" — re-run with `previous_draft` +
  `previous_feedback`, resuming from the saved `research_notes` /
  `seo_brief`.
- Span-draft editing of the "Final copy" (mirrors `/drafts*`), against
  the area's own draft store + `targeted-editor` copy.

The shell types, streaming, Markdown render and `base.html` are reused;
no Job Application module is imported.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from starlette.concurrency import run_in_threadpool

from dashboard import _auth
from dashboard._auth import is_authed
from dashboard._render import make_templates
from dashboard._streaming import stream_run
from dashboard.areas.content_creation_team import (
    _briefs,
    _content_drafts,
    _content_targeted_edit,
)
from dashboard.areas.content_creation_team import _content_team
from dashboard.areas.content_creation_team.pages.content_creation_team import (
    DEFAULT_HOUSE_STYLE,
    PAGE,
    brief_kwargs,
)

# Two routers combined at the end of the module: the span-draft routes go
# on `router` first so a `POST /content/drafts` matches `draft_open`, not
# `brief_save` (`/content/{brief_id}` would otherwise capture "drafts").
router = APIRouter()
_briefs_router = APIRouter()

_HERE = Path(__file__).resolve().parent
_TEMPLATES_DIR = _HERE / "templates"

# The routes this area declares — the single source for `AREA.allowed_routes`
# and the guardrail cross-check in tests/test_guardrails.py.
ROUTES = frozenset(
    {
        "/content",
        "/content/new",
        "/content/{brief_id}",
        "/content/{brief_id}/delete",
        "/content/{brief_id}/run",
        "/content/{brief_id}/send-back",
        "/content/drafts",
        "/content/drafts/{draft_id}",
        "/content/drafts/{draft_id}/revise",
        "/content/drafts/{draft_id}/accept",
        "/content/drafts/{draft_id}/undo",
        "/content/drafts/{draft_id}/edit",
        "/content/drafts/{draft_id}/download",
        "/content/drafts/{draft_id}/save",
    }
)

_templates = make_templates(_TEMPLATES_DIR)
# Shown in the topbar of every area page. A one-area app knows its own nav;
# revisit when a third area lands and the shell owns an area registry.
_AREA_NAV = [("Content Creation Team", "/content")]


def _guard(request: Request) -> RedirectResponse | None:
    if is_authed(request):
        return None
    return RedirectResponse(f"/login?next={quote(request.url.path)}", status_code=303)


def _uid(request: Request) -> str:
    return _auth.current_user_id(request)


def _render(name: str, request: Request, /, status_code: int = 200, **ctx):
    ctx.setdefault(
        "user_email", u.email if (u := _auth.current_user(request)) else None
    )
    ctx.setdefault("stub_runs", request.app.state.stub_runs)
    ctx.setdefault("area_nav", _AREA_NAV)
    return _templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _section_slug(heading: str) -> str:
    return (heading or "").lower().replace(" ", "-")


# --- piece persistence -------------------------------------------------


def _piece_payload(output) -> dict:
    """Everything the brief-detail view needs to re-render a finished
    piece, plus the raw Output fields a "send back" run resumes from."""
    return {
        "sections": [
            {"heading": s.heading, "markdown": s.markdown, "editable": s.editable}
            for s in PAGE.sections(output)
        ],
        "meta": _content_team.cost_meta(output),
        "saved_at": _now_iso(),
        "final_copy": output.final_copy,
        "research_notes": output.research_notes,
        "seo_brief": output.seo_brief,
        "title": output.title,
        "excerpt": output.excerpt,
        "slug": output.slug,
        "tags": list(output.tags),
        "approved": output.approved,
        "stopped_on": output.stopped_on,
        "revision_history": [
            {
                "round": rd.round,
                "editor_verdict": rd.editor_verdict,
                "editor_notes": rd.editor_notes,
                "seo_verdict": rd.seo_verdict,
                "seo_notes": rd.seo_notes,
            }
            for rd in output.revision_history
        ],
    }


def _run_summary(output, payload: dict) -> dict:
    return {
        "saved_at": payload["saved_at"],
        "stopped_on": output.stopped_on,
        "approved": output.approved,
        "cost_usd": payload["meta"]["cost_usd"],
        "title": output.title,
    }


def _persist(brief_id: str, user_id: str):
    """An `on_complete(output)` for `stream_run`: save the piece onto the
    brief and append a run summary. Best-effort (stream_run logs a failure)."""

    def on_complete(output) -> None:
        brief = _briefs.get_brief(brief_id, user_id)
        if brief is None:
            return
        payload = _piece_payload(output)
        runs = [*(brief.runs or []), _run_summary(output, payload)]
        _briefs.update_brief(brief_id, user_id, piece=payload, runs=runs)

    return on_complete


def _result_sections(piece: dict):
    """`(sections, meta)` from a stored `piece`, for the detail view."""
    from dashboard.pages._spec import RunMeta, Section

    sections = [
        Section(
            heading=str(s.get("heading") or ""),
            markdown=str(s.get("markdown") or ""),
            editable=bool(s.get("editable", True)),
        )
        for s in (piece.get("sections") or [])
        if isinstance(s, dict)
    ]
    raw_meta = piece.get("meta")
    meta = (
        RunMeta(
            capability=str(raw_meta.get("capability") or ""),
            capability_version=str(raw_meta.get("capability_version") or ""),
            cost_usd=float(raw_meta.get("cost_usd") or 0.0),
            input_tokens=int(raw_meta.get("input_tokens") or 0),
            output_tokens=int(raw_meta.get("output_tokens") or 0),
            cache_read_input_tokens=int(raw_meta.get("cache_read_input_tokens") or 0),
            cache_write_input_tokens=int(raw_meta.get("cache_write_input_tokens") or 0),
        )
        if isinstance(raw_meta, dict) and raw_meta
        else None
    )
    return sections, meta


# --- Content briefs CRUD --------------------------------------------------


@_briefs_router.get("/content", response_class=HTMLResponse)
async def briefs_list(request: Request):
    if (redirect := _guard(request)) is not None:
        return redirect
    briefs = await run_in_threadpool(_briefs.list_briefs, _uid(request))
    return _render("content_briefs.html", request, briefs=briefs)


@_briefs_router.get("/content/new", response_class=HTMLResponse)
def brief_new(request: Request):
    if (redirect := _guard(request)) is not None:
        return redirect
    return _render("content_brief_form.html", request, values={}, errors={})


@_briefs_router.post("/content/new", response_class=HTMLResponse)
async def brief_create(request: Request):
    if (redirect := _guard(request)) is not None:
        return redirect
    form = await request.form()
    values = {
        "title": str(form.get("title") or "").strip(),
        "goal": str(form.get("goal") or "").strip(),
        "content_brief": str(form.get("content_brief") or "").strip(),
    }
    errors = {k: f"{k.replace('_', ' ').capitalize()} is required." for k, v in values.items() if not v}
    if errors:
        return _render(
            "content_brief_form.html", request, status_code=422,
            values=values, errors=errors,
        )
    brief = await run_in_threadpool(
        _briefs.create_brief,
        values["title"], values["goal"], values["content_brief"], _uid(request),
    )
    return RedirectResponse(f"/content/{brief.id}", status_code=303)


def _brief_detail_ctx(request: Request, brief, **extra):
    piece = brief.piece if isinstance(brief.piece, dict) else None
    sections, meta = _result_sections(piece) if piece else ([], None)
    ctx = dict(
        brief=brief,
        brief_id=brief.id,  # _content_result_panel.html carries it onto a draft
        values={},
        errors={},
        piece=piece,
        sections=sections,
        meta=meta,
        runs=brief.runs or [],
        page=PAGE,
        house_style_default=DEFAULT_HOUSE_STYLE,
    )
    ctx.update(extra)
    return ctx


@_briefs_router.get("/content/{brief_id}", response_class=HTMLResponse)
async def brief_detail(request: Request, brief_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    brief = await run_in_threadpool(_briefs.get_brief, brief_id, _uid(request))
    if brief is None:
        raise HTTPException(status_code=404)
    return _render(
        "content_brief_detail.html", request, **_brief_detail_ctx(request, brief)
    )


_INT_FIELDS = ("target_length_words", "max_editor_revisions", "max_seo_revisions")


@_briefs_router.post("/content/{brief_id}", response_class=HTMLResponse)
async def brief_save(request: Request, brief_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    uid = _uid(request)
    brief = await run_in_threadpool(_briefs.get_brief, brief_id, uid)
    if brief is None:
        raise HTTPException(status_code=404)
    form = await request.form()

    def s(name: str) -> str:
        return str(form.get(name) or "").strip()

    required = {"title": s("title"), "goal": s("goal"), "content_brief": s("content_brief")}
    errors = {
        k: f"{k.replace('_', ' ').capitalize()} is required."
        for k, v in required.items()
        if not v
    }

    def as_int(name: str, default: int) -> int:
        raw = s(name)
        if not raw:
            return default
        try:
            return max(0, int(raw))
        except ValueError:
            errors[name] = "Must be a whole number."
            return default

    def as_float(name: str, default: float) -> float:
        raw = s(name)
        if not raw:
            return default
        try:
            return max(0.0, float(raw))
        except ValueError:
            errors[name] = "Must be a number."
            return default

    updates = dict(
        **required,
        topic_areas=str(form.get("topic_areas") or "").strip(),
        audience=s("audience"),
        audience_brief=str(form.get("audience_brief") or "").strip(),
        call_to_action=str(form.get("call_to_action") or "").strip(),
        target_keywords=str(form.get("target_keywords") or "").strip(),
        house_style=str(form.get("house_style") or "").strip(),
        target_length_words=as_int("target_length_words", 0),
        max_editor_revisions=as_int("max_editor_revisions", 5),
        max_seo_revisions=as_int("max_seo_revisions", 3),
        max_usd=as_float("max_usd", 2.0),
    )
    if errors:
        # Re-render with the submitted values kept.
        merged = {**{f: getattr(brief, f) for f in updates}, **updates}
        return _render(
            "content_brief_detail.html", request, status_code=422,
            **_brief_detail_ctx(request, brief, values=merged, errors=errors),
        )
    updated = await run_in_threadpool(
        lambda: _briefs.update_brief(brief_id, uid, **updates)
    )
    if updated is None:
        raise HTTPException(status_code=404)
    return RedirectResponse(f"/content/{brief_id}", status_code=303)


@_briefs_router.post("/content/{brief_id}/delete", response_class=HTMLResponse)
async def brief_delete(request: Request, brief_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    await run_in_threadpool(_briefs.delete_brief, brief_id, _uid(request))
    return RedirectResponse("/content", status_code=303)


# --- run & revise -------------------------------------------------------


def _stream(request: Request, data, brief_id: str, uid: str):
    user_email = u.email if (u := _auth.current_user(request)) else None
    return stream_run(
        request,
        _templates,
        PAGE,
        data,
        user_email=user_email,
        on_complete=_persist(brief_id, uid),
        context={"brief_id": brief_id, "area_nav": _AREA_NAV},
        template_open="_content_running_open.html",
        template_close="_content_running_close.html",
        template_error="_content_running_error.html",
    )


@_briefs_router.post("/content/{brief_id}/run", response_class=HTMLResponse)
async def brief_run(request: Request, brief_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    uid = _uid(request)
    brief = await run_in_threadpool(_briefs.get_brief, brief_id, uid)
    if brief is None:
        raise HTTPException(status_code=404)
    data = _content_team.build_input(**brief_kwargs(brief))
    if request.app.state.stub_runs:
        return _render(
            "content_brief_detail.html", request,
            **_brief_detail_ctx(
                request, brief,
                piece={"stub": True},
                sections=PAGE.sections(PAGE.example_output),
                meta=PAGE.run_meta(PAGE.example_output),
            ),
        )
    return _stream(request, data, brief_id, uid)


@_briefs_router.post("/content/{brief_id}/send-back", response_class=HTMLResponse)
async def brief_send_back(request: Request, brief_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    uid = _uid(request)
    brief = await run_in_threadpool(_briefs.get_brief, brief_id, uid)
    if brief is None:
        raise HTTPException(status_code=404)
    piece = brief.piece if isinstance(brief.piece, dict) else None
    if not piece or not piece.get("final_copy"):
        raise HTTPException(status_code=400, detail="This brief has no finished piece yet.")
    form = await request.form()
    notes = str(form.get("notes") or "")
    feedback = [
        _content_team.Feedback(comment=line.strip())
        for line in notes.splitlines()
        if line.strip()
    ]
    quote_text = str(form.get("quote") or "").strip()
    quote_comment = str(form.get("quote_comment") or "").strip()
    if quote_text and quote_comment:
        feedback.append(_content_team.Feedback(comment=quote_comment, quote=quote_text))
    if not feedback:
        raise HTTPException(status_code=422, detail="Add at least one note.")
    data = _content_team.build_input(
        **brief_kwargs(brief),
        previous_draft=piece["final_copy"],
        previous_feedback=feedback,
        research_notes=piece.get("research_notes") or None,
        seo_brief=piece.get("seo_brief") or None,
    )
    if request.app.state.stub_runs:
        return _render(
            "content_brief_detail.html", request,
            **_brief_detail_ctx(
                request, brief,
                piece={"stub": True},
                sections=PAGE.sections(PAGE.example_output),
                meta=PAGE.run_meta(PAGE.example_output),
            ),
        )
    return _stream(request, data, brief_id, uid)


# --- span-draft editing (mirrors /drafts*) -----------------------------


def _draft_state(draft) -> dict:
    return {
        "current": draft.current,
        "revision_count": len(draft.revisions),
        "can_undo": bool(draft.revisions),
    }


@router.post("/content/drafts", response_class=HTMLResponse)
async def draft_open(request: Request):
    if (redirect := _guard(request)) is not None:
        return redirect
    form = await request.form()
    slug = str(form.get("slug") or "").strip()
    section = str(form.get("section") or "").strip()
    text = str(form.get("text") or "")
    content_brief_id = str(form.get("content_brief_id") or "").strip()
    if not slug or not section or not text.strip():
        raise HTTPException(status_code=422, detail="slug, section and text are required")
    draft = await run_in_threadpool(
        _content_drafts.create_or_get_draft,
        slug, section, text, _uid(request), content_brief_id,
    )
    return RedirectResponse(f"/content/drafts/{draft.id}", status_code=303)


@router.get("/content/drafts/{draft_id}", response_class=HTMLResponse)
async def draft_edit(request: Request, draft_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    draft = await run_in_threadpool(_content_drafts.get_draft, draft_id, _uid(request))
    if draft is None:
        raise HTTPException(status_code=404)
    return _render(
        "content_draft.html", request,
        draft=draft,
        capability=_content_targeted_edit.CAPABILITY,
        capability_version=_content_targeted_edit.capability_version(),
    )


@router.post("/content/drafts/{draft_id}/revise")
async def draft_revise(request: Request, draft_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    uid = _uid(request)
    draft = await run_in_threadpool(_content_drafts.get_draft, draft_id, uid)
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
    span = _content_drafts.resolve_span(draft.current, selection, span_start, span_len)
    if span is None:
        return JSONResponse(
            {"error": "The selected text is no longer in the draft — reselect and try again."},
            status_code=409,
        )
    span_start, span_len = span
    if request.app.state.stub_runs:
        proposed = _content_targeted_edit.Revision(
            revised=f"[stubbed revision] {selection.strip()}",
            note="Stub mode — no capability call.",
            cost=_content_targeted_edit.Cost(),
        )
    else:
        try:
            proposed = await run_in_threadpool(
                _content_targeted_edit.revise,
                draft.current, selection, instruction,
                kind=_content_targeted_edit.kind_for_section(draft.section),
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


@router.post("/content/drafts/{draft_id}/accept")
async def draft_accept(request: Request, draft_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    uid = _uid(request)
    draft = await run_in_threadpool(_content_drafts.get_draft, draft_id, uid)
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
    span = _content_drafts.resolve_span(draft.current, selection, span_start, span_len)
    if span is None:
        return JSONResponse(
            {"error": "The selected text is no longer in the draft — reselect and try again."},
            status_code=409,
        )
    span_start, span_len = span
    updated = await run_in_threadpool(
        lambda: _content_drafts.record_revision(
            draft_id, uid,
            instruction=instruction, selection=selection,
            span_start=span_start, span_len=span_len,
            revised=revised, note=note, cost=cost,
        )
    )
    if updated is None:
        raise HTTPException(status_code=404)
    return JSONResponse(_draft_state(updated))


@router.post("/content/drafts/{draft_id}/undo")
async def draft_undo(request: Request, draft_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    updated = await run_in_threadpool(
        _content_drafts.undo_last, draft_id, _uid(request)
    )
    if updated is None:
        raise HTTPException(status_code=404)
    return JSONResponse(_draft_state(updated))


@router.post("/content/drafts/{draft_id}/edit")
async def draft_manual_edit(request: Request, draft_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    form = await request.form()
    text = str(form.get("text") or "")
    if not text.strip():
        return JSONResponse({"error": "The draft can't be empty."}, status_code=422)
    updated = await run_in_threadpool(
        lambda: _content_drafts.record_manual_edit(draft_id, _uid(request), text=text)
    )
    if updated is None:
        raise HTTPException(status_code=404)
    return JSONResponse(_draft_state(updated))


@router.get("/content/drafts/{draft_id}/download")
async def draft_download(request: Request, draft_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    draft = await run_in_threadpool(_content_drafts.get_draft, draft_id, _uid(request))
    if draft is None:
        raise HTTPException(status_code=404)
    name = f"{draft.slug}-{draft.section}".strip("-") or "draft"
    return Response(
        content=draft.current,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
    )


def _piece_with_section(piece: dict, section: str, text: str) -> dict:
    """`piece` with the section whose slug is `section` swapped for `text`
    (cost meta and the other sections untouched, `saved_at` bumped). If it
    is the `final-copy` section, `piece['final_copy']` is updated too, so a
    later send-back carries the edit. Builds a minimal one-section payload
    when nothing usable is stored."""
    now = _now_iso()
    if isinstance(piece, dict) and piece.get("sections"):
        sections = []
        patched = False
        for raw in piece["sections"]:
            s = dict(raw) if isinstance(raw, dict) else {}
            if _section_slug(str(s.get("heading") or "")) == section:
                s["markdown"] = text
                patched = True
            sections.append(s)
        if patched:
            out = {**piece, "sections": sections, "saved_at": now}
            if section == "final-copy":
                out["final_copy"] = text
            return out
    heading, editable = section, True
    for s in PAGE.sections(PAGE.example_output):
        if _section_slug(s.heading) == section:
            heading, editable = s.heading, s.editable
            break
    out = {
        "sections": [{"heading": heading, "markdown": text, "editable": editable}],
        "meta": None,
        "saved_at": now,
    }
    if section == "final-copy":
        out["final_copy"] = text
    return out


@router.post("/content/drafts/{draft_id}/save")
async def draft_save(request: Request, draft_id: str):
    if (redirect := _guard(request)) is not None:
        return redirect
    uid = _uid(request)
    draft = await run_in_threadpool(_content_drafts.get_draft, draft_id, uid)
    if draft is None:
        raise HTTPException(status_code=404)
    if not draft.content_brief_id:
        raise HTTPException(status_code=400, detail="This draft is not linked to a brief.")
    brief = await run_in_threadpool(_briefs.get_brief, draft.content_brief_id, uid)
    if brief is None:
        raise HTTPException(status_code=404)
    piece = brief.piece if isinstance(brief.piece, dict) else {}
    patched = _piece_with_section(piece, draft.section, draft.current)
    await run_in_threadpool(
        lambda: _briefs.update_brief(draft.content_brief_id, uid, piece=patched)
    )
    return RedirectResponse(
        f"/content/{quote(draft.content_brief_id)}", status_code=303
    )


# Draft routes (on `router`) are already registered above; append the
# briefs routes after them so the static `/content/drafts` path wins the
# match over `/content/{brief_id}`. A plain `.extend` (rather than
# `include_router`) keeps every route a flat `APIRoute` on `router.routes`
# — no prefix/tags/deps to merge — so the guardrail can introspect them.
router.routes.extend(_briefs_router.routes)
