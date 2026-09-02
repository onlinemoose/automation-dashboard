"""The shape of a dashboard page.

A `Page` mirrors one capability's contract and nothing else:

- `fields`        -> the capability's `Input` (one form field per argument)
- `build_input`   -> turns the submitted form into that `Input`. Takes the
                     current user's id as a second argument, so it can
                     resolve keys into the app's own per-user stores
                     (`job_post_id`, `background_document_ids`). That id is
                     app plumbing, never a capability `Input` field — the
                     same documented category as those two form keys.
- `run`           -> the capability's `run()` (the only call into it)
- `sections`      -> turns its `Output` into headed blocks of Markdown
- `example_form`  -> a valid demo submission (also powers "Load example")
- `example_output`-> a canned `Output`, so tests exercise the page offline

If filling any of these in means reaching past the capability's front
door, or teaching the page how the work is done, the boundary is wrong.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

# Widgets the generic form renderer knows how to draw.
#   "text"      - single-line input
#   "textarea"  - multi-line box
#   "number"    - single-line numeric input
#   "lines"     - multi-line box; each non-blank line is one list item
#   "checklist"  - one checkbox per saved document; the submitted value is
#                  a list of document ids (read with FormReader.multi)
#   "doc_picker" - a <select> of saved documents; the submitted value is one
#                  document id (read with FormReader.text). "" means none.
#   "hidden"     - an <input type="hidden">, no label or wrapper. Its value
#                  comes from the URL / a prior submission, not the user —
#                  e.g. `job_post_id`, carried from `?job_post_id=<id>`.
Widget = str


class FormError(Exception):
    """Raised by `build_input` when the submitted form can't be used.

    Carries `{field_name: message}` so the form re-renders with each
    problem shown next to its field.
    """

    def __init__(self, errors: Mapping[str, str]) -> None:
        self.errors: dict[str, str] = dict(errors)
        super().__init__("; ".join(f"{k}: {v}" for k, v in self.errors.items()))


@dataclass(frozen=True)
class Field:
    name: str  # must match the capability Input argument name
    label: str
    widget: Widget = "textarea"
    required: bool = False
    help: str = ""
    placeholder: str = ""
    # When the writer page is opened with `?job_post_id=<id>`, this field's
    # value is pre-filled (server-side) from the named attribute of that
    # `JobPost` — e.g. `from_job_post="company"`. The field stays a normal
    # editable input; the value is a starting point, not a lock. Left None
    # for fields that don't derive from a job post. Like `job_post_id`
    # itself, this is app-storage plumbing, not part of the contract.
    from_job_post: str | None = None


@dataclass(frozen=True)
class Section:
    heading: str
    markdown: str
    # Whether this section can be opened as a working draft (the "Edit
    # draft" button on the result view). True for the primary output a
    # page produces; set False for a secondary, explanatory section — a
    # targeting note, a summary — that is only ever read or downloaded.
    editable: bool = True


@dataclass(frozen=True)
class RunMeta:
    """What one `run()` cost, pulled from the capability's `Output`.

    Rendered as a small footer on the result page and — later — written to
    the app's own usage store so spend can be totalled across runs. It is a
    *usage* record, not a content archive: numbers plus which capability
    (and pinned version) produced them, nothing else.
    """

    capability: str  # the capability's distribution name, e.g. "cover-letter-writer"
    capability_version: str  # the pinned tag, e.g. "v0.10.0"
    cost_usd: float  # the capability's own estimate
    input_tokens: int
    output_tokens: int  # includes the model's thinking tokens
    cache_read_input_tokens: int
    cache_write_input_tokens: int


@dataclass
class Page:
    slug: str
    title: str
    summary: str
    fields: Sequence[Field]
    example_form: Mapping[str, str]
    example_output: object
    build_input: Callable[[Mapping[str, str], str], object]
    run: Callable[[object], object]
    sections: Callable[[object], list[Section]]
    # Optional: map the capability's `Output` to a `RunMeta` for the cost
    # footer. Pages whose capability reports no cost leave this `None`.
    run_meta: Callable[[object], RunMeta] | None = None
    # Set on pages whose `run()` routinely takes minutes (a long-form
    # document from one LLM call). The submit route then streams a holding
    # view immediately and keeps the connection warm while `run()` works,
    # so a hosting proxy's time-to-first-byte timeout can't kill the
    # request. Quick pages (sub-minute) leave this False and get a plain
    # response. See docs/EXPERIENCE.md ("Slow pages").
    slow: bool = False
    # Set when this page's capability `run()` accepts a keyword-only
    # `on_progress` callback (a `Progress` value ~2x/sec while it streams).
    # Only meaningful with `slow=True`: the streamed holding view then
    # shows a live word count instead of a bare spinner.
    progress: bool = False
    # For a job-post-driven page: the `job_posts` column a finished run is
    # saved to (one of `dashboard._jobs.RESULT_SLOTS`). When set, a
    # completed run is stored against the job post it was written for, and
    # re-opening the page for that post (`?job_post_id=…`) shows the saved
    # result in place of a blank form — `?rerun=1` forces the form. Pages
    # not driven by a job post leave this None. See docs/JOB_POSTS.md.
    saved_result_slot: str | None = None


class FormReader:
    """Small helper for `build_input`: reads fields, collects problems,
    raises one `FormError` with all of them at `done()`."""

    def __init__(self, form: Mapping[str, str]) -> None:
        self._form = form
        self._errors: dict[str, str] = {}

    def text(self, name: str, label: str, *, required: bool = False) -> str | None:
        value = (self._form.get(name) or "").strip()
        if not value:
            if required:
                self._errors[name] = f"{label} is required."
            return None
        return value

    def integer(self, name: str, label: str) -> int | None:
        raw = (self._form.get(name) or "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            self._errors[name] = f"{label} must be a whole number."
            return None

    def lines(self, name: str) -> list[str]:
        raw = self._form.get(name) or ""
        return [line.strip() for line in raw.splitlines() if line.strip()]

    def multi(self, name: str) -> list[str]:
        """Every submitted value for a repeated field (e.g. a "checklist").

        Works whether the form is a multidict (`getlist`) or a plain dict
        whose value is already a list or a scalar. Falsy entries are dropped.
        Never errors, never required.
        """
        form = self._form
        if hasattr(form, "getlist"):
            values = form.getlist(name)
        else:
            value = form.get(name)
            values = value if isinstance(value, list) else [value]
        return [str(v).strip() for v in values if v and str(v).strip()]

    def done(self) -> None:
        if self._errors:
            raise FormError(self._errors)
