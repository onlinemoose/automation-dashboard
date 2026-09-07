"""The Content Creation Team area's own store for working drafts — a
finished piece the user is revising span by span, kept so the edit
survives a reload.

A self-contained copy of `dashboard/_drafts.py` (an area owns its span
editor rather than importing the Job Application one). Same shape and
backend-selection: a Supabase table `content_drafts` reached with the
service-role key, falling back to an in-process dict when `SUPABASE_URL`
/ `SUPABASE_SERVICE_KEY` are unset. Rows are scoped per user.

One draft per `(user_id, slug, section, source_hash)` — re-opening the
same result section returns the same draft. `original` is the section as
`run()` first produced it and is never mutated; `current` is `original`
with every accepted revision spliced in, in order. **Undo is replay.**
Linear history only. See `docs/CONTENT_BRIEFS.md`.
"""

from __future__ import annotations

import hashlib
import os
import threading
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol

_TABLE = "content_drafts"


def normalize(text: str) -> str:
    """Canonical form for stored draft text: Unix newlines only."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n")


def source_hash(text: str) -> str:
    """The dedupe key for a run's output — sha256 of the normalised text."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def apply_revision(current: str, span_start: int, span_len: int, revised: str) -> str:
    """Splice `revised` in where `current[span_start:span_start+span_len]` was."""
    start = max(0, min(span_start, len(current)))
    end = max(start, min(start + max(0, span_len), len(current)))
    return current[:start] + revised + current[end:]


@dataclass(frozen=True)
class Revision:
    """One accepted span revision, recorded for audit and undo-by-replay.

    `span_start` / `span_len` are offsets into the `current` text at the
    moment this revision was applied — replaying the list in order
    reproduces them exactly.
    """

    at: datetime
    instruction: str
    selection: str
    span_start: int
    span_len: int
    revised: str
    note: str
    cost: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "at": self.at.isoformat(),
            "instruction": self.instruction,
            "selection": self.selection,
            "span_start": self.span_start,
            "span_len": self.span_len,
            "revised": self.revised,
            "note": self.note,
            "cost": self.cost,
        }

    @staticmethod
    def from_dict(d: dict) -> "Revision":
        return Revision(
            at=_parse_ts(d.get("at")) or datetime.now(timezone.utc),
            instruction=str(d.get("instruction") or ""),
            selection=str(d.get("selection") or ""),
            span_start=int(d.get("span_start") or 0),
            span_len=int(d.get("span_len") or 0),
            revised=str(d.get("revised") or ""),
            note=str(d.get("note") or ""),
            cost=dict(d.get("cost") or {}),
        )


@dataclass(frozen=True)
class Draft:
    id: str
    slug: str  # the page that produced it — always "content-creation-team"
    section: str  # the Output section slug, e.g. "final-copy"
    source_hash: str
    original: str  # as run() first produced it — never mutated
    current: str  # original + every accepted revision, in order
    revisions: list[Revision] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    user_id: str = ""  # the Supabase auth.users id that owns this row
    # The content brief this piece was written for — set so the editor's
    # "Save to brief" can write the edited text back into that brief's
    # `piece`. "" for a draft opened from a result with no brief behind it.
    content_brief_id: str = ""


def replay(original: str, revisions: list[Revision]) -> str:
    """`original` with each revision spliced in, in order."""
    text = original
    for rev in revisions:
        text = apply_revision(text, rev.span_start, rev.span_len, rev.revised)
    return text


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class _Backend(Protocol):
    def create_or_get(
        self, slug: str, section: str, text: str, user_id: str, content_brief_id: str = ""
    ) -> Draft: ...
    def get(self, draft_id: str, user_id: str) -> Draft | None: ...
    def add_revision(
        self, draft_id: str, rev: Revision, user_id: str
    ) -> Draft | None: ...
    def undo(self, draft_id: str, user_id: str) -> Draft | None: ...


class _MemoryBackend:
    """Non-persistent fallback. Mirrors the Supabase backend's `user_id`
    filtering exactly: a draft belonging to another user is invisible."""

    def __init__(self) -> None:
        self._drafts: dict[str, Draft] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def create_or_get(
        self, slug: str, section: str, text: str, user_id: str, content_brief_id: str = ""
    ) -> Draft:
        digest = source_hash(text)
        with self._lock:
            for draft in self._drafts.values():
                if (draft.user_id, draft.slug, draft.section, draft.source_hash) == (
                    user_id, slug, section, digest,
                ):
                    if content_brief_id and not draft.content_brief_id:
                        draft = replace(
                            draft,
                            content_brief_id=content_brief_id,
                            updated_at=datetime.now(timezone.utc),
                        )
                        self._drafts[draft.id] = draft
                    return draft
            self._seq += 1
            now = datetime.now(timezone.utc)
            draft = Draft(
                id=f"mem-{self._seq}",
                slug=slug,
                section=section,
                source_hash=digest,
                original=text,
                current=text,
                revisions=[],
                created_at=now,
                updated_at=now,
                user_id=user_id,
                content_brief_id=content_brief_id,
            )
            self._drafts[draft.id] = draft
            return draft

    def get(self, draft_id: str, user_id: str) -> Draft | None:
        draft = self._drafts.get(draft_id)
        return draft if draft is not None and draft.user_id == user_id else None

    def add_revision(self, draft_id: str, rev: Revision, user_id: str) -> Draft | None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None or draft.user_id != user_id:
                return None
            revisions = [*draft.revisions, rev]
            updated = _with_revisions(draft, revisions)
            self._drafts[draft_id] = updated
            return updated

    def undo(self, draft_id: str, user_id: str) -> Draft | None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None or draft.user_id != user_id:
                return None
            if not draft.revisions:
                return draft
            updated = _with_revisions(draft, list(draft.revisions[:-1]))
            self._drafts[draft_id] = updated
            return updated


class _SupabaseBackend:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)

    def _table(self):
        return self._client.table(_TABLE)

    @staticmethod
    def _row(row: dict) -> Draft:
        raw = row.get("revisions")
        if isinstance(raw, str):  # jsonb sometimes arrives as text
            import json

            try:
                raw = json.loads(raw)
            except ValueError:
                raw = []
        revisions = [Revision.from_dict(r) for r in (raw or []) if isinstance(r, dict)]
        return Draft(
            id=str(row["id"]),
            slug=row.get("slug") or "",
            section=row.get("section") or "",
            source_hash=row.get("source_hash") or "",
            original=row.get("original") or "",
            current=row.get("current") or "",
            revisions=revisions,
            created_at=_parse_ts(row.get("created_at")),
            updated_at=_parse_ts(row.get("updated_at")),
            user_id=row.get("user_id") or "",
            content_brief_id=row.get("content_brief_id") or "",
        )

    def create_or_get(
        self, slug: str, section: str, text: str, user_id: str, content_brief_id: str = ""
    ) -> Draft:
        digest = source_hash(text)
        res = (
            self._table()
            .select("*")
            .eq("user_id", user_id)
            .eq("slug", slug)
            .eq("section", section)
            .eq("source_hash", digest)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            existing = self._row(rows[0])
            if content_brief_id and not existing.content_brief_id:
                upd = (
                    self._table()
                    .update({"content_brief_id": content_brief_id})
                    .eq("id", existing.id)
                    .eq("user_id", user_id)
                    .execute()
                )
                bumped = upd.data or []
                return self._row(bumped[0]) if bumped else existing
            return existing
        res = (
            self._table()
            .insert(
                {
                    "slug": slug,
                    "section": section,
                    "source_hash": digest,
                    "original": text,
                    "current": text,
                    "revisions": [],
                    "user_id": user_id,
                    "content_brief_id": content_brief_id or None,
                }
            )
            .execute()
        )
        return self._row((res.data or [{}])[0])

    def get(self, draft_id: str, user_id: str) -> Draft | None:
        res = (
            self._table()
            .select("*")
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def _save(
        self, draft_id: str, revisions: list[Revision], current: str, user_id: str
    ) -> Draft | None:
        res = (
            self._table()
            .update(
                {
                    "revisions": [r.to_dict() for r in revisions],
                    "current": current,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def add_revision(self, draft_id: str, rev: Revision, user_id: str) -> Draft | None:
        draft = self.get(draft_id, user_id)
        if draft is None:
            return None
        revisions = [*draft.revisions, rev]
        return self._save(draft_id, revisions, replay(draft.original, revisions), user_id)

    def undo(self, draft_id: str, user_id: str) -> Draft | None:
        draft = self.get(draft_id, user_id)
        if draft is None:
            return None
        if not draft.revisions:
            return draft
        revisions = list(draft.revisions[:-1])
        return self._save(draft_id, revisions, replay(draft.original, revisions), user_id)


def _with_revisions(draft: Draft, revisions: list[Revision]) -> Draft:
    return replace(
        draft,
        revisions=revisions,
        current=replay(draft.original, revisions),
        updated_at=datetime.now(timezone.utc),
    )


_backend: _Backend | None = None
_backend_lock = threading.Lock()


def _store() -> _Backend:
    """The backing store, chosen once from the environment."""
    global _backend
    if _backend is not None:
        return _backend
    with _backend_lock:
        if _backend is None:
            url = os.environ.get("SUPABASE_URL")
            key = os.environ.get("SUPABASE_SERVICE_KEY")
            if url and key:
                _backend = _SupabaseBackend(url, key)
            else:
                warnings.warn(
                    "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set — content "
                    "drafts are held in memory and will not survive a restart. "
                    "Set both in the environment for anything real.",
                    stacklevel=2,
                )
                _backend = _MemoryBackend()
    return _backend


def reset() -> None:
    """Drop the chosen backend so it is re-selected. For tests only."""
    global _backend
    with _backend_lock:
        _backend = None


# --- public API: thin pass-throughs, user_id required, no default --------


def create_or_get_draft(
    slug: str, section: str, text: str, user_id: str, content_brief_id: str = ""
) -> Draft:
    return _store().create_or_get(
        slug, section, normalize(text), user_id, content_brief_id
    )


def get_draft(draft_id: str, user_id: str) -> Draft | None:
    return _store().get(draft_id, user_id)


def record_revision(
    draft_id: str,
    user_id: str,
    *,
    instruction: str,
    selection: str,
    span_start: int,
    span_len: int,
    revised: str,
    note: str = "",
    cost: dict | None = None,
) -> Draft | None:
    rev = Revision(
        at=datetime.now(timezone.utc),
        instruction=instruction,
        selection=selection,
        span_start=span_start,
        span_len=span_len,
        revised=revised,
        note=note,
        cost=dict(cost or {}),
    )
    return _store().add_revision(draft_id, rev, user_id)


def undo_last(draft_id: str, user_id: str) -> Draft | None:
    return _store().undo(draft_id, user_id)


MANUAL_EDIT = "(manual edit)"  # the `instruction` recorded for a hand edit


def record_manual_edit(draft_id: str, user_id: str, *, text: str) -> Draft | None:
    """Record a free-form edit of the whole draft as one revision — slots
    into undo-by-replay like any other, so `original` stays immutable.

    Returns the updated draft; the draft unchanged when `text` matches
    `current`; None if `draft_id` is unknown or owned by someone else.
    """
    draft = _store().get(draft_id, user_id)
    if draft is None:
        return None
    text = normalize(text)
    if text == draft.current:
        return draft
    rev = Revision(
        at=datetime.now(timezone.utc),
        instruction=MANUAL_EDIT,
        selection=draft.current,
        span_start=0,
        span_len=len(draft.current),
        revised=text,
        note="",
        cost={},
    )
    return _store().add_revision(draft_id, rev, user_id)


def resolve_span(
    current: str, selection: str, span_start: int, span_len: int
) -> tuple[int, int] | None:
    """Where `selection` sits in `current`, as (start, len). Trust the
    browser offsets when they still line up; else locate the selection
    text if it occurs exactly once; else None. (Copy of the shell's
    `dashboard/app.py::_resolve_span` — generic text logic the area owns
    with its span editor.)"""
    if selection and current[span_start : span_start + span_len] == selection:
        return span_start, span_len
    if selection:
        first = current.find(selection)
        if first != -1 and current.find(selection, first + 1) == -1:
            return first, len(selection)
    return None
