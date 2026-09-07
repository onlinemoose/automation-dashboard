"""The Content Creation Team area's span editor: the app's own draft
store (a copy of `dashboard/_drafts.py`), the splice, undo-by-replay, and
the revision routes. `stub_editor` monkeypatches `targeted_editor.run` so
the suite stays offline (as in `test_drafts.py`).
"""

from __future__ import annotations

import pytest
import targeted_editor
from starlette.testclient import TestClient

from dashboard.app import create_app
from dashboard.areas.content_creation_team import _briefs, _content_drafts

USER = "test-user"
OTHER = "other-user"

SLUG = "content-creation-team"
SECTION = "final-copy"
TEXT = "The quick brown fox jumps over the lazy dog.\n\nA second paragraph follows here."


@pytest.fixture(autouse=True)
def fresh_store():
    _content_drafts.reset()
    _briefs.reset()
    yield
    _content_drafts.reset()
    _briefs.reset()


@pytest.fixture(autouse=True)
def stub_editor(monkeypatch):
    def fake_run(data: targeted_editor.Input) -> targeted_editor.Output:
        return targeted_editor.Output(
            revised=data.selection.upper(),
            note="stubbed — upper-cased the span",
            cost=targeted_editor.Cost(usd=0.0012, input_tokens=40, output_tokens=8,
                                      cache_read_input_tokens=0, cache_write_input_tokens=12),
        )

    monkeypatch.setattr(targeted_editor, "run", fake_run)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


# --- the splice + replay (pure) --------------------------------------


def test_apply_revision_and_replay():
    assert _content_drafts.apply_revision("hello world", 6, 5, "there") == "hello there"
    assert _content_drafts.apply_revision("abc", 1, 0, "-") == "a-bc"
    r = _content_drafts.Revision(
        at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        instruction="i", selection="world", span_start=6, span_len=5, revised="THERE",
        note="", cost={},
    )
    assert _content_drafts.replay("hello world", [r]) == "hello THERE"


# --- the store -----------------------------------------------------


def test_dedupe_and_brief_backfill():
    a = _content_drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    b = _content_drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER, "brief-1")
    assert a.id == b.id  # same (user, slug, section, hash)
    assert b.content_brief_id == "brief-1"  # backfilled, not part of the key
    c = _content_drafts.create_or_get_draft(SLUG, SECTION, TEXT, OTHER)
    assert c.id != a.id  # different user -> different draft


def test_foreign_draft_is_invisible():
    d = _content_drafts.create_or_get_draft(SLUG, SECTION, TEXT, OTHER)
    assert _content_drafts.get_draft(d.id, USER) is None
    assert _content_drafts.record_manual_edit(d.id, USER, text="x") is None
    assert _content_drafts.undo_last(d.id, USER) is None


# --- the routes --------------------------------------------------


def _open(client: TestClient, brief_id: str = "") -> str:
    r = client.post(
        "/content/drafts",
        data={"slug": SLUG, "section": SECTION, "text": TEXT, "content_brief_id": brief_id},
        follow_redirects=False,
    )
    assert r.status_code == 303
    return r.headers["location"]


def test_open_edit_revise_accept_undo(client: TestClient):
    loc = _open(client)
    body = client.get(loc).text
    assert 'id="draft-doc"' in body and "content-draft-edit.js" in body

    did = loc.rsplit("/", 1)[-1]
    r = client.post(f"/content/drafts/{did}/revise", data={
        "selection": "quick brown", "span_start": TEXT.index("quick brown"),
        "span_len": len("quick brown"), "instruction": "shout it",
    })
    assert r.status_code == 200 and r.json()["revised"] == "QUICK BROWN"
    # not mutated yet
    assert _content_drafts.get_draft(did, USER).current == TEXT

    r = client.post(f"/content/drafts/{did}/accept", data={
        "selection": "quick brown", "span_start": TEXT.index("quick brown"),
        "span_len": len("quick brown"), "instruction": "shout it",
        "revised": "QUICK BROWN", "note": "n", "cost": "{}",
    })
    assert r.status_code == 200 and r.json()["revision_count"] == 1
    assert "QUICK BROWN" in _content_drafts.get_draft(did, USER).current

    r = client.post(f"/content/drafts/{did}/undo")
    assert r.json()["revision_count"] == 0
    assert _content_drafts.get_draft(did, USER).current == TEXT


def test_revise_409_when_selection_is_gone(client: TestClient):
    did = _open(client).rsplit("/", 1)[-1]
    r = client.post(f"/content/drafts/{did}/revise", data={
        "selection": "not in the text", "span_start": 0, "span_len": 5,
        "instruction": "x",
    })
    assert r.status_code == 409 and "reselect" in r.json()["error"]


def test_manual_edit_and_download(client: TestClient):
    did = _open(client).rsplit("/", 1)[-1]
    r = client.post(f"/content/drafts/{did}/edit", data={"text": "brand new body"})
    assert r.status_code == 200 and r.json()["revision_count"] == 1
    r = client.get(f"/content/drafts/{did}/download")
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text == "brand new body"
    assert client.post(f"/content/drafts/{did}/edit", data={"text": "  "}).status_code == 422


def test_foreign_draft_routes_are_404(client: TestClient):
    other = TestClient(create_app(auth_disabled=True, as_user=OTHER))
    did = _open(other).rsplit("/", 1)[-1]
    assert client.get(f"/content/drafts/{did}").status_code == 404
    assert client.get(f"/content/drafts/{did}/download").status_code == 404
    assert client.post(f"/content/drafts/{did}/undo").status_code == 404


# --- save to brief ---------------------------------------------


def _brief_with_piece(final_copy: str = TEXT) -> _briefs.ContentBrief:
    brief = _briefs.create_brief("T", "g" * 20, "b" * 20, USER)
    piece = {
        "sections": [
            {"heading": "Publishing metadata", "markdown": "meta", "editable": False},
            {"heading": "Final copy", "markdown": final_copy, "editable": True},
        ],
        "meta": None,
        "saved_at": "2026-09-06T00:00:00Z",
        "final_copy": final_copy,
        "research_notes": "RN", "seo_brief": "SB",
    }
    return _briefs.update_brief(brief.id, USER, piece=piece)


def test_save_to_brief_patches_final_copy_and_the_section(client: TestClient):
    brief = _brief_with_piece()
    did = _open(client, brief.id).rsplit("/", 1)[-1]
    client.post(f"/content/drafts/{did}/edit", data={"text": "the edited piece"})
    r = client.post(f"/content/drafts/{did}/save", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/content/{brief.id}"
    piece = _briefs.get_brief(brief.id, USER).piece
    assert piece["final_copy"] == "the edited piece"
    fc = next(s for s in piece["sections"] if s["heading"] == "Final copy")
    assert fc["markdown"] == "the edited piece"
    meta = next(s for s in piece["sections"] if s["heading"] == "Publishing metadata")
    assert meta["markdown"] == "meta"  # untouched


def test_save_needs_a_linked_brief(client: TestClient):
    did = _open(client).rsplit("/", 1)[-1]  # no brief id
    assert client.post(f"/content/drafts/{did}/save").status_code == 400


def test_stub_mode_revise_is_canned():
    client = TestClient(create_app(auth_disabled=True, stub_runs=True))
    did = _open(client).rsplit("/", 1)[-1]
    r = client.post(f"/content/drafts/{did}/revise", data={
        "selection": "quick brown", "span_start": TEXT.index("quick brown"),
        "span_len": len("quick brown"), "instruction": "x",
    })
    assert r.status_code == 200 and "stub" in r.json()["note"].lower()
