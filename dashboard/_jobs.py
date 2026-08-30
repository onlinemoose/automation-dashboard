"""The app's own store for Job posts — a pasted posting, its analysis, and
the user's annotations, kept once so both writer pages can pull from it.

This is app-owned storage (CLAUDE.md rule 6), private to the dashboard and
written up in `docs/JOB_POSTS.md`. Capabilities never see it; the writer
pages read it only to resolve a picked id to `job_posting` text and an
`emphasis` list.

Same shape and backend-selection as `dashboard/_documents.py`: a Supabase
(Postgres) table `job_posts` reached with the service-role key, falling
back to an in-process dict (with a `warnings.warn`) when `SUPABASE_URL` /
`SUPABASE_SERVICE_KEY` are unset, so local dev and the test suite run
without Supabase (nothing persists across restarts).
"""

from __future__ import annotations

import os
import threading
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

_TABLE = "job_posts"


@dataclass(frozen=True)
class JobPost:
    id: str
    title: str  # user-set label, e.g. "Acme — Product Lead"
    posting: str  # the raw job posting text
    emphasis: str  # the annotated emphasis list (">" quote / "-" note format); "" until analysed
    updated_at: datetime | None = None


def _parse_ts(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class _Backend(Protocol):
    def list(self) -> list[JobPost]: ...
    def get(self, job_id: str) -> JobPost | None: ...
    def create(self, title: str, posting: str) -> JobPost: ...
    def update(
        self,
        job_id: str,
        *,
        title: str | None = None,
        posting: str | None = None,
        emphasis: str | None = None,
    ) -> JobPost | None: ...
    def delete(self, job_id: str) -> None: ...


class _MemoryBackend:
    """Non-persistent fallback. Only used when Supabase isn't configured."""

    def __init__(self) -> None:
        self._jobs: dict[str, JobPost] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def list(self) -> list[JobPost]:
        return sorted(self._jobs.values(), key=lambda j: j.title.lower())

    def get(self, job_id: str) -> JobPost | None:
        return self._jobs.get(job_id)

    def create(self, title: str, posting: str) -> JobPost:
        with self._lock:
            self._seq += 1
            job = JobPost(
                id=f"mem-{self._seq}",
                title=title,
                posting=posting,
                emphasis="",
                updated_at=datetime.now(timezone.utc),
            )
            self._jobs[job.id] = job
            return job

    def update(
        self,
        job_id: str,
        *,
        title: str | None = None,
        posting: str | None = None,
        emphasis: str | None = None,
    ) -> JobPost | None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is None:
                return None
            job = JobPost(
                id=job_id,
                title=current.title if title is None else title,
                posting=current.posting if posting is None else posting,
                emphasis=current.emphasis if emphasis is None else emphasis,
                updated_at=datetime.now(timezone.utc),
            )
            self._jobs[job_id] = job
            return job

    def delete(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)


class _SupabaseBackend:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)

    def _table(self):
        return self._client.table(_TABLE)

    @staticmethod
    def _row(row: dict) -> JobPost:
        return JobPost(
            id=str(row["id"]),
            title=row.get("title") or "",
            posting=row.get("posting") or "",
            emphasis=row.get("emphasis") or "",
            updated_at=_parse_ts(row.get("updated_at")),
        )

    def list(self) -> list[JobPost]:
        res = self._table().select("*").order("title").execute()
        return [self._row(r) for r in (res.data or [])]

    def get(self, job_id: str) -> JobPost | None:
        res = self._table().select("*").eq("id", job_id).limit(1).execute()
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def create(self, title: str, posting: str) -> JobPost:
        res = self._table().insert({"title": title, "posting": posting}).execute()
        return self._row((res.data or [{}])[0])

    def update(
        self,
        job_id: str,
        *,
        title: str | None = None,
        posting: str | None = None,
        emphasis: str | None = None,
    ) -> JobPost | None:
        payload: dict[str, object] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if title is not None:
            payload["title"] = title
        if posting is not None:
            payload["posting"] = posting
        if emphasis is not None:
            payload["emphasis"] = emphasis
        res = self._table().update(payload).eq("id", job_id).execute()
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def delete(self, job_id: str) -> None:
        self._table().delete().eq("id", job_id).execute()


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
                    "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set — Job posts "
                    "are held in memory and will not survive a restart. Set both "
                    "in the environment for anything real.",
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


def list_job_posts() -> list[JobPost]:
    return _store().list()


def get_job_post(job_id: str) -> JobPost | None:
    return _store().get(job_id)


def create_job_post(title: str, posting: str) -> JobPost:
    return _store().create(title, posting)


def update_job_post(
    job_id: str,
    *,
    title: str | None = None,
    posting: str | None = None,
    emphasis: str | None = None,
) -> JobPost | None:
    return _store().update(job_id, title=title, posting=posting, emphasis=emphasis)


def delete_job_post(job_id: str) -> None:
    _store().delete(job_id)
