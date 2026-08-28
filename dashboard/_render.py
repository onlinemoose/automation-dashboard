"""Turn the Markdown a capability returns into HTML for the results view."""

from __future__ import annotations

import markdown as _markdown
from markupsafe import Markup


def to_html(text: str) -> Markup:
    html = _markdown.markdown(text or "", extensions=["extra", "sane_lists", "nl2br"])
    return Markup(html)
