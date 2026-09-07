"""Turn the Markdown a capability returns into HTML for the results view,
plus the one shared way to build a `Jinja2Templates` for the shell or an
area (same filters, same `asset_v` cache-bust, an area's own template dir
first and the shell's `templates/` behind it so `{% extends "base.html" %}`
resolves)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import markdown as _markdown
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

_HERE = Path(__file__).resolve().parent
_SHELL_TEMPLATES = _HERE / "templates"
_STATIC = _HERE / "static"


def to_html(text: str) -> Markup:
    html = _markdown.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])
    return Markup(html)


def asset_version() -> str:
    """Short hash of the static assets, appended as `?v=` to their URLs so
    a browser fetches the new file after a deploy instead of a stale cache."""
    h = hashlib.sha1()
    for name in ("app.css", "draft-edit.js", "content-draft-edit.js"):
        try:
            h.update((_STATIC / name).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:8]


def make_templates(*extra_dirs: Path | str) -> Jinja2Templates:
    """A `Jinja2Templates` wired the way the whole app expects: the
    `markdown` / `thousands` / `usd4` filters and the `asset_v` global.
    `extra_dirs` come first in the search path, the shell's `templates/`
    last — so an area can override or extend a shell template and still
    `{% extends "base.html" %}`."""
    directories = [str(d) for d in extra_dirs] + [str(_SHELL_TEMPLATES)]
    templates = Jinja2Templates(directory=directories)
    templates.env.filters["markdown"] = to_html
    templates.env.filters["thousands"] = lambda n: f"{int(n):,}"
    templates.env.filters["usd4"] = lambda n: f"${float(n):.4f}"
    templates.env.globals["asset_v"] = asset_version()
    return templates
