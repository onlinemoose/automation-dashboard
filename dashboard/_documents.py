"""The app's own store for Background documents — reusable notes that feed
the writer pages' `background_documents` input.

This is app-owned storage (CLAUDE.md rule 6), private to the dashboard and
written up in `docs/BACKGROUND_DOCUMENTS.md`. Capabilities never see it;
pages read it only to resolve a picked id to its text.

Backing store: a Supabase (Postgres) table `background_documents`, reached
with the service-role key. If `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` are
unset the module falls back to an in-process dict and warns — the same
shape as the ephemeral `SESSION_SECRET` fallback in `app.py`, so local dev
and the test suite run without Supabase (nothing persists across restarts).

Rows are scoped per user: every method takes the owning `user_id` and
every query filters on it, reads and writes alike. See
`docs/USER_SCOPING.md`.

If the store ever needs to move (a different Postgres), swap the
internals here — page code and routes don't change.
"""

from __future__ import annotations

import os
import threading
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

_TABLE = "background_documents"


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    body: str
    updated_at: datetime | None = None
    user_id: str = ""  # the Supabase auth.users id that owns this row


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class _Backend(Protocol):
    def list(self, user_id: str) -> list[Document]: ...
    def get_many(self, ids: Iterable[str], user_id: str) -> list[Document]: ...
    def get(self, doc_id: str, user_id: str) -> Document | None: ...
    def create(self, title: str, body: str, user_id: str) -> Document: ...
    def update(
        self, doc_id: str, title: str, body: str, user_id: str
    ) -> Document | None: ...
    def delete(self, doc_id: str, user_id: str) -> None: ...


class _MemoryBackend:
    """Non-persistent fallback. Only used when Supabase isn't configured.

    Mirrors the Supabase backend's `user_id` filtering exactly: a row
    belonging to another user is invisible, not merely unlisted.
    """

    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def list(self, user_id: str) -> list[Document]:
        mine = [d for d in self._docs.values() if d.user_id == user_id]
        return sorted(mine, key=lambda d: d.title.lower())

    def get_many(self, ids: Iterable[str], user_id: str) -> list[Document]:
        wanted = [i for i in ids if i]
        found = [
            self._docs[i]
            for i in wanted
            if i in self._docs and self._docs[i].user_id == user_id
        ]
        return sorted(found, key=lambda d: d.title.lower())

    def get(self, doc_id: str, user_id: str) -> Document | None:
        doc = self._docs.get(doc_id)
        return doc if doc is not None and doc.user_id == user_id else None

    def create(self, title: str, body: str, user_id: str) -> Document:
        with self._lock:
            self._seq += 1
            doc = Document(
                id=f"mem-{self._seq}",
                title=title,
                body=body,
                updated_at=datetime.now(timezone.utc),
                user_id=user_id,
            )
            self._docs[doc.id] = doc
            return doc

    def update(self, doc_id: str, title: str, body: str, user_id: str) -> Document | None:
        with self._lock:
            current = self._docs.get(doc_id)
            if current is None or current.user_id != user_id:
                return None
            doc = Document(
                id=doc_id,
                title=title,
                body=body,
                updated_at=datetime.now(timezone.utc),
                user_id=current.user_id,  # the rebuilt row keeps its owner
            )
            self._docs[doc_id] = doc
            return doc

    def delete(self, doc_id: str, user_id: str) -> None:
        with self._lock:
            current = self._docs.get(doc_id)
            if current is not None and current.user_id == user_id:
                del self._docs[doc_id]


class _SupabaseBackend:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)

    def _table(self):
        return self._client.table(_TABLE)

    @staticmethod
    def _row(row: dict) -> Document:
        return Document(
            id=str(row["id"]),
            title=row.get("title") or "",
            body=row.get("body") or "",
            updated_at=_parse_ts(row.get("updated_at")),
            user_id=row.get("user_id") or "",
        )

    def list(self, user_id: str) -> list[Document]:
        res = self._table().select("*").eq("user_id", user_id).order("title").execute()
        return [self._row(r) for r in (res.data or [])]

    def get_many(self, ids: Iterable[str], user_id: str) -> list[Document]:
        wanted = [i for i in ids if i]
        if not wanted:
            return []
        res = (
            self._table()
            .select("*")
            .in_("id", wanted)
            .eq("user_id", user_id)
            .order("title")
            .execute()
        )
        return [self._row(r) for r in (res.data or [])]

    def get(self, doc_id: str, user_id: str) -> Document | None:
        res = (
            self._table()
            .select("*")
            .eq("id", doc_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def create(self, title: str, body: str, user_id: str) -> Document:
        res = (
            self._table()
            .insert({"title": title, "body": body, "user_id": user_id})
            .execute()
        )
        return self._row((res.data or [{}])[0])

    def update(self, doc_id: str, title: str, body: str, user_id: str) -> Document | None:
        payload = {
            "title": title,
            "body": body,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        res = (
            self._table()
            .update(payload)
            .eq("id", doc_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def delete(self, doc_id: str, user_id: str) -> None:
        self._table().delete().eq("id", doc_id).eq("user_id", user_id).execute()


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
                    "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set — Background "
                    "documents are held in memory and will not survive a restart. "
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
#
# Every one of these takes the owning user's id as its last required
# argument, with no default — a missed call site is a loud TypeError at
# import/collection time rather than a silent cross-user read.


def list_documents(user_id: str) -> list[Document]:
    return _store().list(user_id)


def get_documents(ids: Iterable[str], user_id: str) -> list[Document]:
    return _store().get_many(ids, user_id)


def get_document(doc_id: str, user_id: str) -> Document | None:
    return _store().get(doc_id, user_id)


def create_document(title: str, body: str, user_id: str) -> Document:
    return _store().create(title, body, user_id)


def update_document(doc_id: str, title: str, body: str, user_id: str) -> Document | None:
    return _store().update(doc_id, title, body, user_id)


def delete_document(doc_id: str, user_id: str) -> None:
    _store().delete(doc_id, user_id)
