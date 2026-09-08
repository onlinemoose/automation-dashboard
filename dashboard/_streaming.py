"""Stream a `slow=True` page's result.

A minutes-long `run()` would blow a hosting proxy's time-to-first-byte /
idle timeout before the response could start. `stream_run` flushes a
holding view straight away, keeps the connection warm while `run()` works
in a worker thread (a `window.__progress(...)` script per update for a
`progress=True` page, a bare keepalive comment otherwise), then streams
the real result markup plus a script that swaps it in. Headers are
already sent by the time `run()` could fail, so a failure is rendered
into the body, not as a 5xx.

This is shell plumbing (docs/AREAS.md: "auth, the generic `/p/{slug}`
page contract, streaming, Markdown render …"). The shell's `/p/{slug}`
submit and every area's own run route call it — parameterised by the
holding/close/error templates and a completion callback, so nothing about
the streaming loop is copied per area.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool

if TYPE_CHECKING:  # a leaf module — importing the page registry here would cycle
    from dashboard.pages._spec import Page

_log = logging.getLogger("dashboard")

# Flush a keepalive at least this often. Anything well under a hosting
# proxy's response timeout (Render's is ~100s) works.
_KEEPALIVE_SECONDS = 15


def stream_run(
    request: Request,
    templates: Jinja2Templates,
    page: "Page",
    data: object,
    *,
    user_email: str | None = None,
    on_complete: Callable[[object], None] | None = None,
    context: dict | None = None,
    template_open: str = "_running_open.html",
    template_close: str = "_running_close.html",
    template_error: str = "_running_error.html",
) -> StreamingResponse:
    """Run `page.run(data)` behind a streamed holding view.

    `on_complete(output)` — if given — is run in a worker thread once
    `run()` returns, before the result is flushed; it is best-effort (a
    failure is logged, never sinks the rendered result). `context` is
    merged into every template render (e.g. `job_post_id` / `brief_id`
    for the crumb and the result panel's links).
    """
    tpl = templates.get_template
    ctx = dict(context or {})

    async def body():
        yield tpl(template_open).render(page=page, user_email=user_email, **ctx)

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
            yield tpl(template_error).render(
                page=page, error=type(exc).__name__, user_email=user_email, **ctx
            )
            return
        if on_complete is not None:
            try:
                await run_in_threadpool(on_complete, output)
            except Exception:  # noqa: BLE001 - a save must not sink the result
                _log.exception("slow page %s: on_complete failed", page.slug)
        meta = page.run_meta(output) if page.run_meta else None
        yield tpl(template_close).render(
            page=page, sections=page.sections(output), meta=meta,
            user_email=user_email, **ctx,
        )

    return StreamingResponse(
        body(),
        media_type="text/html; charset=utf-8",
        # ask intermediate proxies not to buffer the trickle
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
