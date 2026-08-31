"""The app's own store for working drafts — a capability result the user
is revising span by span, kept so the edit survives a page reload.

This is app-owned storage (CLAUDE.md rule 6), private to the dashboard
and written up in `docs/DRAFTS.md`. Capabilities never see it; the
targeted-revision seam reads a draft's `current` text, calls the
`targeted-editor` capability, and writes the accepted revision back here.

Same shape and backend-selection as `dashboard/_jobs.py`: a Supabase
(Postgres) table `drafts` reached with the service-role key, falling back
to an in-process dict (with a `warnings.warn`) when `SUPABASE_URL` /
`SUPABASE_SERVICE_KEY` are unset, so local dev and the test suite run
without Supabase (nothing persists across restarts).

One draft per `(slug, section, source_hash)` — re-opening the same result
returns the same working draft. `original` is the result exactly as
`run()` first produced it and is never mutated; `current` is `original`
with every accepted revision spliced in, in order. **Undo is replay:**
drop the last revision and recompute `current` from `original` + what
remains. Linear history only — one edit in flight at a time.
"""

from __future__ import annotations

import hashlib
import os
import threading
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

_TABLE = "drafts"


def source_hash(text: str) -> str:
    """The dedupe key for a run's output — sha256 of the exact text."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def apply_revision(current: str, span_start: int, span_len: int, revised: str) -> str:
    """Splice `revised` in where `current[span_start:span_start+span_len]` was.

    The one piece of real text logic the app owns. Because it is one edit
    at a time and the user accepts before selecting again, every new
    selection is taken against the freshly updated `current` — there are
    no pending offsets to rebase.
    """
    start = max(0, min(span_start, len(current)))
    end = max(start, min(start + max(0, span_len), len(current)))
    return current[:start] + revised + current[end:]


@dataclass(frozen=True)
class Revision:
    """One accepted span revision, recorded for audit and undo-by-replay.

    `span_start` / `span_len` are offsets into the `current` text at the
    moment this revision was applied — i.e. `original` with every earlier
    revision already spliced in. Replaying the list in order reproduces
    those offsets exactly.
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
    slug: str  # the capability page that produced it, e.g. "cover-letter-writer"
    section: str  # the Output section, e.g. "cover-letter"
    source_hash: str
    original: str  # as run() first produced it — never mutated
    current: str  # original + every accepted revision, in order
    revisions: list[Revision] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    def create_or_get(self, slug: str, section: str, text: str) -> Draft: ...
    def get(self, draft_id: str) -> Draft | None: ...
    def add_revision(self, draft_id: str, rev: Revision) -> Draft | None: ...
    def undo(self, draft_id: str) -> Draft | None: ...


class _MemoryBackend:
    """Non-persistent fallback. Only used when Supabase isn't configured."""

    def __init__(self) -> None:
        self._drafts: dict[str, Draft] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def create_or_get(self, slug: str, section: str, text: str) -> Draft:
        digest = source_hash(text)
        with self._lock:
            for draft in self._drafts.values():
                if (draft.slug, draft.section, draft.source_hash) == (slug, section, digest):
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
            )
            self._drafts[draft.id] = draft
            return draft

    def get(self, draft_id: str) -> Draft | None:
        return self._drafts.get(draft_id)

    def add_revision(self, draft_id: str, rev: Revision) -> Draft | None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
                return None
            revisions = [*draft.revisions, rev]
            updated = _with_revisions(draft, revisions)
            self._drafts[draft_id] = updated
            return updated

    def undo(self, draft_id: str) -> Draft | None:
        with self._lock:
            draft = self._drafts.get(draft_id)
            if draft is None:
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
        )

    def create_or_get(self, slug: str, section: str, text: str) -> Draft:
        digest = source_hash(text)
        res = (
            self._table()
            .select("*")
            .eq("slug", slug)
            .eq("section", section)
            .eq("source_hash", digest)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if rows:
            return self._row(rows[0])
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
                }
            )
            .execute()
        )
        return self._row((res.data or [{}])[0])

    def get(self, draft_id: str) -> Draft | None:
        res = self._table().select("*").eq("id", draft_id).limit(1).execute()
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def _save(self, draft_id: str, revisions: list[Revision], current: str) -> Draft | None:
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
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def add_revision(self, draft_id: str, rev: Revision) -> Draft | None:
        draft = self.get(draft_id)
        if draft is None:
            return None
        revisions = [*draft.revisions, rev]
        return self._save(draft_id, revisions, replay(draft.original, revisions))

    def undo(self, draft_id: str) -> Draft | None:
        draft = self.get(draft_id)
        if draft is None:
            return None
        if not draft.revisions:
            return draft
        revisions = list(draft.revisions[:-1])
        return self._save(draft_id, revisions, replay(draft.original, revisions))


def _with_revisions(draft: Draft, revisions: list[Revision]) -> Draft:
    from dataclasses import replace

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
                    "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set — working "
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


# --- public API: thin pass-throughs to the chosen backend ----------------


def create_or_get_draft(slug: str, section: str, text: str) -> Draft:
    return _store().create_or_get(slug, section, text)


def get_draft(draft_id: str) -> Draft | None:
    return _store().get(draft_id)


def record_revision(
    draft_id: str,
    *,
    instruction: str,
    selection: str,
    span_start: int,
    span_len: int,
    revised: str,
    note: str = "",
    cost: dict | None = None,
) -> Draft | None:
    """Append an accepted revision and re-splice `current`. Returns the
    updated draft, or None if `draft_id` is unknown."""
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
    return _store().add_revision(draft_id, rev)


def undo_last(draft_id: str) -> Draft | None:
    """Drop the last revision and replay. No-op if there are none.
    Returns the updated draft, or None if `draft_id` is unknown."""
    return _store().undo(draft_id)
