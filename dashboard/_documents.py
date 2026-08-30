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

If the store ever needs to move (real accounts, a different Postgres),
swap the internals here — page code and routes don't change.
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


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class _Backend(Protocol):
    def list(self) -> list[Document]: ...
    def get_many(self, ids: Iterable[str]) -> list[Document]: ...
    def get(self, doc_id: str) -> Document | None: ...
    def create(self, title: str, body: str) -> Document: ...
    def update(self, doc_id: str, title: str, body: str) -> Document | None: ...
    def delete(self, doc_id: str) -> None: ...


class _MemoryBackend:
    """Non-persistent fallback. Only used when Supabase isn't configured."""

    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def list(self) -> list[Document]:
        return sorted(self._docs.values(), key=lambda d: d.title.lower())

    def get_many(self, ids: Iterable[str]) -> list[Document]:
        wanted = [i for i in ids if i]
        found = [self._docs[i] for i in wanted if i in self._docs]
        return sorted(found, key=lambda d: d.title.lower())

    def get(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def create(self, title: str, body: str) -> Document:
        with self._lock:
            self._seq += 1
            doc = Document(
                id=f"mem-{self._seq}",
                title=title,
                body=body,
                updated_at=datetime.now(timezone.utc),
            )
            self._docs[doc.id] = doc
            return doc

    def update(self, doc_id: str, title: str, body: str) -> Document | None:
        with self._lock:
            if doc_id not in self._docs:
                return None
            doc = Document(
                id=doc_id,
                title=title,
                body=body,
                updated_at=datetime.now(timezone.utc),
            )
            self._docs[doc_id] = doc
            return doc

    def delete(self, doc_id: str) -> None:
        self._docs.pop(doc_id, None)


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
        )

    def list(self) -> list[Document]:
        res = self._table().select("*").order("title").execute()
        return [self._row(r) for r in (res.data or [])]

    def get_many(self, ids: Iterable[str]) -> list[Document]:
        wanted = [i for i in ids if i]
        if not wanted:
            return []
        res = self._table().select("*").in_("id", wanted).order("title").execute()
        return [self._row(r) for r in (res.data or [])]

    def get(self, doc_id: str) -> Document | None:
        res = self._table().select("*").eq("id", doc_id).limit(1).execute()
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def create(self, title: str, body: str) -> Document:
        res = self._table().insert({"title": title, "body": body}).execute()
        return self._row((res.data or [{}])[0])

    def update(self, doc_id: str, title: str, body: str) -> Document | None:
        payload = {
            "title": title,
            "body": body,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        res = self._table().update(payload).eq("id", doc_id).execute()
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def delete(self, doc_id: str) -> None:
        self._table().delete().eq("id", doc_id).execute()


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


def list_documents() -> list[Document]:
    return _store().list()


def get_documents(ids: Iterable[str]) -> list[Document]:
    return _store().get_many(ids)


def get_document(doc_id: str) -> Document | None:
    return _store().get(doc_id)


def create_document(title: str, body: str) -> Document:
    return _store().create(title, body)


def update_document(doc_id: str, title: str, body: str) -> Document | None:
    return _store().update(doc_id, title, body)


def delete_document(doc_id: str) -> None:
    _store().delete(doc_id)
