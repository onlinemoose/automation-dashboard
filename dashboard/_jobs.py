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

import json
import os
import threading
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

_TABLE = "job_posts"

# The writer-page result slots on a job post — one jsonb column each,
# holding a rendered run (sections + cost meta) so re-opening the page for
# this job post shows the saved result instead of a blank form. `None`
# until that writer has run against this post. See docs/JOB_POSTS.md.
RESULT_SLOTS = ("cover_letter", "tailored_cv")


def _as_result(value: object) -> dict | None:
    """A saved writer result from a jsonb column: a dict, or `None` when
    unset. Postgres jsonb occasionally arrives as a JSON string."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) and value else None


@dataclass(frozen=True)
class JobPost:
    id: str
    title: str  # user-set label, e.g. "Acme — Product Lead"
    posting: str  # the raw job posting text
    emphasis: str  # the annotated emphasis list (">" quote / "-" note format); "" until analysed
    summary: str = ""  # the analysis summary (Markdown); "" until analysed and saved
    # Saved writer results, keyed by the page's `saved_result_slot`. `None`
    # until that writer runs against this post; a dict of {sections, meta,
    # saved_at} once it has. App-owned display data, never capability input.
    cover_letter: dict | None = None
    tailored_cv: dict | None = None
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
    def list(self, user_id: str) -> list[JobPost]: ...
    def get(self, job_id: str, user_id: str) -> JobPost | None: ...
    def create(self, title: str, posting: str, user_id: str) -> JobPost: ...
    def update(
        self,
        job_id: str,
        user_id: str,
        *,
        title: str | None = None,
        posting: str | None = None,
        emphasis: str | None = None,
        summary: str | None = None,
        cover_letter: dict | None = None,
        tailored_cv: dict | None = None,
    ) -> JobPost | None: ...
    def delete(self, job_id: str, user_id: str) -> None: ...


class _MemoryBackend:
    """Non-persistent fallback. Only used when Supabase isn't configured.

    Mirrors the Supabase backend's `user_id` filtering exactly: a row
    belonging to another user is invisible, not merely unlisted.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobPost] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def list(self, user_id: str) -> list[JobPost]:
        mine = [j for j in self._jobs.values() if j.user_id == user_id]
        return sorted(mine, key=lambda j: j.title.lower())

    def get(self, job_id: str, user_id: str) -> JobPost | None:
        job = self._jobs.get(job_id)
        return job if job is not None and job.user_id == user_id else None

    def create(self, title: str, posting: str, user_id: str) -> JobPost:
        with self._lock:
            self._seq += 1
            job = JobPost(
                id=f"mem-{self._seq}",
                title=title,
                posting=posting,
                emphasis="",
                summary="",
                updated_at=datetime.now(timezone.utc),
                user_id=user_id,
            )
            self._jobs[job.id] = job
            return job

    def update(
        self,
        job_id: str,
        user_id: str,
        *,
        title: str | None = None,
        posting: str | None = None,
        emphasis: str | None = None,
        summary: str | None = None,
        cover_letter: dict | None = None,
        tailored_cv: dict | None = None,
    ) -> JobPost | None:
        with self._lock:
            current = self._jobs.get(job_id)
            # The get-before-merge is scoped too — otherwise a foreign row
            # would be read, merged, and written back under its own id.
            if current is None or current.user_id != user_id:
                return None
            job = JobPost(
                id=job_id,
                title=current.title if title is None else title,
                posting=current.posting if posting is None else posting,
                emphasis=current.emphasis if emphasis is None else emphasis,
                summary=current.summary if summary is None else summary,
                cover_letter=current.cover_letter if cover_letter is None else cover_letter,
                tailored_cv=current.tailored_cv if tailored_cv is None else tailored_cv,
                updated_at=datetime.now(timezone.utc),
                user_id=current.user_id,  # the rebuilt row keeps its owner
            )
            self._jobs[job_id] = job
            return job

    def delete(self, job_id: str, user_id: str) -> None:
        with self._lock:
            current = self._jobs.get(job_id)
            if current is not None and current.user_id == user_id:
                del self._jobs[job_id]


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
            summary=row.get("summary") or "",
            cover_letter=_as_result(row.get("cover_letter")),
            tailored_cv=_as_result(row.get("tailored_cv")),
            updated_at=_parse_ts(row.get("updated_at")),
            user_id=row.get("user_id") or "",
        )

    def list(self, user_id: str) -> list[JobPost]:
        res = self._table().select("*").eq("user_id", user_id).order("title").execute()
        return [self._row(r) for r in (res.data or [])]

    def get(self, job_id: str, user_id: str) -> JobPost | None:
        res = (
            self._table()
            .select("*")
            .eq("id", job_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def create(self, title: str, posting: str, user_id: str) -> JobPost:
        res = (
            self._table()
            .insert({"title": title, "posting": posting, "user_id": user_id})
            .execute()
        )
        return self._row((res.data or [{}])[0])

    def update(
        self,
        job_id: str,
        user_id: str,
        *,
        title: str | None = None,
        posting: str | None = None,
        emphasis: str | None = None,
        summary: str | None = None,
        cover_letter: dict | None = None,
        tailored_cv: dict | None = None,
    ) -> JobPost | None:
        payload: dict[str, object] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        if title is not None:
            payload["title"] = title
        if posting is not None:
            payload["posting"] = posting
        if emphasis is not None:
            payload["emphasis"] = emphasis
        if summary is not None:
            payload["summary"] = summary
        if cover_letter is not None:
            payload["cover_letter"] = cover_letter
        if tailored_cv is not None:
            payload["tailored_cv"] = tailored_cv
        res = (
            self._table()
            .update(payload)
            .eq("id", job_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def delete(self, job_id: str, user_id: str) -> None:
        self._table().delete().eq("id", job_id).eq("user_id", user_id).execute()


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
#
# Every one of these takes the owning user's id as its last required
# argument, with no default — a missed call site is a loud TypeError at
# import/collection time rather than a silent cross-user read.


def list_job_posts(user_id: str) -> list[JobPost]:
    return _store().list(user_id)


def get_job_post(job_id: str, user_id: str) -> JobPost | None:
    return _store().get(job_id, user_id)


def create_job_post(title: str, posting: str, user_id: str) -> JobPost:
    return _store().create(title, posting, user_id)


def update_job_post(
    job_id: str,
    user_id: str,
    *,
    title: str | None = None,
    posting: str | None = None,
    emphasis: str | None = None,
    summary: str | None = None,
    cover_letter: dict | None = None,
    tailored_cv: dict | None = None,
) -> JobPost | None:
    return _store().update(
        job_id,
        user_id,
        title=title,
        posting=posting,
        emphasis=emphasis,
        summary=summary,
        cover_letter=cover_letter,
        tailored_cv=tailored_cv,
    )


def delete_job_post(job_id: str, user_id: str) -> None:
    _store().delete(job_id, user_id)
