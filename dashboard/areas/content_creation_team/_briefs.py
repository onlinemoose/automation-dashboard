"""The app's own store for Content briefs — a goal, a brief, the optional
knobs, and the finished piece once the content team has run.

App-owned storage (CLAUDE.md rule 6), private to this area and written up
in `docs/CONTENT_BRIEFS.md`. The `content-creation-team` capability never
sees it; the page reads a brief only to resolve it to a plain
`content_creation_team.Input`, and a finished run is saved back onto the
brief so re-opening it shows the piece (and a later revision can resume
from the saved `research_notes` / `seo_brief`).

Same shape and backend-selection as `dashboard/_jobs.py`: a Supabase
(Postgres) table `content_briefs` reached with the service-role key,
falling back to an in-process dict (with a `warnings.warn`) when
`SUPABASE_URL` / `SUPABASE_SERVICE_KEY` are unset, so local dev and the
test suite run without Supabase. Rows are scoped per user: every method
takes the owning `user_id` and every query filters on it, reads and
writes alike (see `docs/USER_SCOPING.md`).
"""

from __future__ import annotations

import json
import os
import threading
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Protocol

_TABLE = "content_briefs"

# The knob columns a partial `update_brief` may set. `title` / `goal` /
# `content_brief` are required-on-create; the rest carry a constant
# default (no NULLs, no `_UNSET` sentinel) so "pass None = leave alone"
# works uniformly. `target_length_words` 0 and `max_usd` 2.0 are the
# "unset" values the page maps back to the contract default.
_STR_KNOBS = (
    "title", "goal", "content_brief", "topic_areas", "audience",
    "audience_brief", "call_to_action", "target_keywords", "house_style",
)
_INT_KNOBS = ("target_length_words", "max_editor_revisions", "max_seo_revisions")
_FLOAT_KNOBS = ("max_usd",)


def _as_json(value: object, empty):
    """A jsonb column read back: parsed, or `empty` when unset/broken.
    Postgres jsonb occasionally arrives as a JSON string."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return empty
    if isinstance(value, dict):
        return value or None if empty is None else value
    if isinstance(value, list):
        return value
    return empty


def _as_piece(value: object) -> dict | None:
    return _as_json(value, None)


def _as_runs(value: object) -> list:
    out = _as_json(value, [])
    return out if isinstance(out, list) else []


@dataclass(frozen=True)
class ContentBrief:
    id: str
    title: str  # user-set label for the list
    goal: str
    content_brief: str
    topic_areas: str = ""  # one tag per line -> Input.topic_areas
    audience: str = ""
    audience_brief: str = ""
    target_length_words: int = 0  # 0 == unset (-> None)
    call_to_action: str = ""
    target_keywords: str = ""  # one keyword per line -> Input.target_keywords
    house_style: str = ""  # free text -> Input.house_style
    max_usd: float = 2.0
    max_editor_revisions: int = 5
    max_seo_revisions: int = 3
    # The current finished piece: the rendered result sections + cost meta,
    # plus the raw Output fields a revision run needs to resume
    # (`final_copy`, `research_notes`, `seo_brief`, …). `None` until the
    # first run. See docs/CONTENT_BRIEFS.md for the shape.
    piece: dict | None = None
    # Append-only run summaries ({saved_at, stopped_on, approved, cost_usd,
    # title}), one per run / send-back — the detail page's history strip.
    runs: list[dict] = field(default_factory=list)
    created_at: datetime | None = None  # list() orders newest-first by this
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
    def list(self, user_id: str) -> list[ContentBrief]: ...
    def get(self, brief_id: str, user_id: str) -> ContentBrief | None: ...
    def create(
        self, title: str, goal: str, content_brief: str, user_id: str
    ) -> ContentBrief: ...
    def update(self, brief_id: str, user_id: str, **fields) -> ContentBrief | None: ...
    def delete(self, brief_id: str, user_id: str) -> None: ...


def _clean_updates(fields: dict) -> dict:
    """The non-None keyword updates, each keyed to a known column."""
    known = set(_STR_KNOBS) | set(_INT_KNOBS) | set(_FLOAT_KNOBS) | {"piece", "runs"}
    return {k: v for k, v in fields.items() if k in known and v is not None}


class _MemoryBackend:
    """Non-persistent fallback. Mirrors the Supabase backend's `user_id`
    filtering exactly: a row belonging to another user is invisible."""

    def __init__(self) -> None:
        self._briefs: dict[str, ContentBrief] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def list(self, user_id: str) -> list[ContentBrief]:
        mine = [b for b in self._briefs.values() if b.user_id == user_id]
        return list(reversed(mine))

    def get(self, brief_id: str, user_id: str) -> ContentBrief | None:
        brief = self._briefs.get(brief_id)
        return brief if brief is not None and brief.user_id == user_id else None

    def create(
        self, title: str, goal: str, content_brief: str, user_id: str
    ) -> ContentBrief:
        with self._lock:
            self._seq += 1
            now = datetime.now(timezone.utc)
            brief = ContentBrief(
                id=f"mem-{self._seq}",
                title=title,
                goal=goal,
                content_brief=content_brief,
                created_at=now,
                updated_at=now,
                user_id=user_id,
            )
            self._briefs[brief.id] = brief
            return brief

    def update(self, brief_id: str, user_id: str, **fields) -> ContentBrief | None:
        with self._lock:
            current = self._briefs.get(brief_id)
            if current is None or current.user_id != user_id:
                return None
            updates = _clean_updates(fields)
            brief = replace(
                current, **updates, updated_at=datetime.now(timezone.utc)
            )
            self._briefs[brief_id] = brief
            return brief

    def delete(self, brief_id: str, user_id: str) -> None:
        with self._lock:
            current = self._briefs.get(brief_id)
            if current is not None and current.user_id == user_id:
                del self._briefs[brief_id]


class _SupabaseBackend:
    def __init__(self, url: str, key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, key)

    def _table(self):
        return self._client.table(_TABLE)

    @staticmethod
    def _row(row: dict) -> ContentBrief:
        return ContentBrief(
            id=str(row["id"]),
            title=row.get("title") or "",
            goal=row.get("goal") or "",
            content_brief=row.get("content_brief") or "",
            topic_areas=row.get("topic_areas") or "",
            audience=row.get("audience") or "",
            audience_brief=row.get("audience_brief") or "",
            target_length_words=int(row.get("target_length_words") or 0),
            call_to_action=row.get("call_to_action") or "",
            target_keywords=row.get("target_keywords") or "",
            house_style=row.get("house_style") or "",
            max_usd=float(row.get("max_usd") if row.get("max_usd") is not None else 2.0),
            max_editor_revisions=int(row.get("max_editor_revisions") or 5),
            max_seo_revisions=int(row.get("max_seo_revisions") or 3),
            piece=_as_piece(row.get("piece")),
            runs=_as_runs(row.get("runs")),
            created_at=_parse_ts(row.get("created_at")),
            updated_at=_parse_ts(row.get("updated_at")),
            user_id=row.get("user_id") or "",
        )

    def list(self, user_id: str) -> list[ContentBrief]:
        res = (
            self._table()
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._row(r) for r in (res.data or [])]

    def get(self, brief_id: str, user_id: str) -> ContentBrief | None:
        res = (
            self._table()
            .select("*")
            .eq("id", brief_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def create(
        self, title: str, goal: str, content_brief: str, user_id: str
    ) -> ContentBrief:
        res = (
            self._table()
            .insert(
                {
                    "title": title,
                    "goal": goal,
                    "content_brief": content_brief,
                    "user_id": user_id,
                }
            )
            .execute()
        )
        return self._row((res.data or [{}])[0])

    def update(self, brief_id: str, user_id: str, **fields) -> ContentBrief | None:
        payload: dict[str, object] = {"updated_at": datetime.now(timezone.utc).isoformat()}
        payload.update(_clean_updates(fields))
        res = (
            self._table()
            .update(payload)
            .eq("id", brief_id)
            .eq("user_id", user_id)
            .execute()
        )
        rows = res.data or []
        return self._row(rows[0]) if rows else None

    def delete(self, brief_id: str, user_id: str) -> None:
        self._table().delete().eq("id", brief_id).eq("user_id", user_id).execute()


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
                    "SUPABASE_URL / SUPABASE_SERVICE_KEY are not set — Content "
                    "briefs are held in memory and will not survive a restart. "
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
# Every one of these takes the owning user's id as a required argument,
# with no default — a missed call site is a loud TypeError at
# import/collection time rather than a silent cross-user read.


def list_briefs(user_id: str) -> list[ContentBrief]:
    return _store().list(user_id)


def get_brief(brief_id: str, user_id: str) -> ContentBrief | None:
    return _store().get(brief_id, user_id)


def create_brief(title: str, goal: str, content_brief: str, user_id: str) -> ContentBrief:
    return _store().create(title, goal, content_brief, user_id)


def update_brief(
    brief_id: str,
    user_id: str,
    *,
    title: str | None = None,
    goal: str | None = None,
    content_brief: str | None = None,
    topic_areas: str | None = None,
    audience: str | None = None,
    audience_brief: str | None = None,
    target_length_words: int | None = None,
    call_to_action: str | None = None,
    target_keywords: str | None = None,
    house_style: str | None = None,
    max_usd: float | None = None,
    max_editor_revisions: int | None = None,
    max_seo_revisions: int | None = None,
    piece: dict | None = None,
    runs: list[dict] | None = None,
) -> ContentBrief | None:
    """Patch a brief. Only the keyword arguments that are not None are
    written; `updated_at` always bumps. Returns the updated brief, or None
    if `brief_id` is unknown or owned by someone else."""
    return _store().update(
        brief_id,
        user_id,
        title=title,
        goal=goal,
        content_brief=content_brief,
        topic_areas=topic_areas,
        audience=audience,
        audience_brief=audience_brief,
        target_length_words=target_length_words,
        call_to_action=call_to_action,
        target_keywords=target_keywords,
        house_style=house_style,
        max_usd=max_usd,
        max_editor_revisions=max_editor_revisions,
        max_seo_revisions=max_seo_revisions,
        piece=piece,
        runs=runs,
    )


def delete_brief(brief_id: str, user_id: str) -> None:
    _store().delete(brief_id, user_id)
