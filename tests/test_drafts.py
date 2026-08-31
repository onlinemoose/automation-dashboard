"""The working-drafts area: the app's own store, the splice, undo-by-replay,
and the targeted-revision routes.

The store falls back to an in-process dict when Supabase isn't configured
(no env vars in the test run). The revision step calls the
`targeted-editor` capability; `stub_editor` below monkeypatches its
`run()` so the suite stays offline, the same way `test_jobs.py` stubs
`job_analyst.run`.
"""

from __future__ import annotations

import pytest
import targeted_editor
from starlette.testclient import TestClient

from dashboard import _drafts
from dashboard.app import create_app

SLUG = "cover-letter-writer"
SECTION = "cover-letter"
TEXT = "The quick brown fox jumps over the lazy dog.\n\nA second paragraph follows here."


@pytest.fixture(autouse=True)
def fresh_store():
    _drafts.reset()
    yield
    _drafts.reset()


@pytest.fixture(autouse=True)
def stub_editor(monkeypatch):
    """Stand in for the targeted-editor LLM call. The 'revision' is the
    selection upper-cased, so a splice is easy to assert."""

    def fake_run(data: targeted_editor.Input) -> targeted_editor.Output:
        return targeted_editor.Output(
            revised=data.selection.upper(),
            note="stubbed — upper-cased the span",
            cost=targeted_editor.Cost(
                usd=0.0012,
                input_tokens=40,
                output_tokens=8,
                cache_read_input_tokens=0,
                cache_write_input_tokens=12,
            ),
        )

    monkeypatch.setattr(targeted_editor, "run", fake_run)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


# --- the splice + replay (pure) -----------------------------------------


def test_apply_revision_splices_at_the_offsets():
    assert _drafts.apply_revision("hello world", 6, 5, "there") == "hello there"
    assert _drafts.apply_revision("abc", 0, 3, "XYZ") == "XYZ"
    assert _drafts.apply_revision("abc", 1, 0, "-") == "a-bc"  # zero-length = insert


def test_apply_revision_clamps_out_of_range_offsets():
    assert _drafts.apply_revision("abc", 10, 5, "Z") == "abcZ"
    assert _drafts.apply_revision("abc", -3, 2, "Z") == "Zc"


def test_replay_reproduces_current_from_original():
    r1 = _drafts.Revision(
        at=None, instruction="i1", selection="quick", span_start=4, span_len=5,
        revised="QUICK", note="", cost={},
    )
    # offsets for r2 are taken against the text *after* r1 (same length here)
    r2 = _drafts.Revision(
        at=None, instruction="i2", selection="lazy", span_start=35, span_len=4,
        revised="LAZY", note="", cost={},
    )
    base = "The quick brown fox jumps over the lazy dog."
    assert _drafts.replay(base, [r1, r2]) == "The QUICK brown fox jumps over the LAZY dog."


# --- the store --------------------------------------------------------


def test_create_or_get_dedupes_on_slug_section_and_hash():
    a = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    b = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    assert a.id == b.id
    assert a.original == a.current == TEXT
    assert a.revisions == []

    # different text -> different draft
    c = _drafts.create_or_get_draft(SLUG, SECTION, TEXT + " more")
    assert c.id != a.id
    # different section -> different draft
    d = _drafts.create_or_get_draft(SLUG, "targeting-note", TEXT)
    assert d.id != a.id


def test_record_revision_appends_and_resplices():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    updated = _drafts.record_revision(
        draft.id,
        instruction="shout the animal",
        selection="fox",
        span_start=TEXT.index("fox"),
        span_len=3,
        revised="FOX",
        note="upper",
        cost={"usd": 0.001},
    )
    assert updated.current == TEXT.replace("fox", "FOX", 1)
    assert len(updated.revisions) == 1
    assert updated.revisions[0].instruction == "shout the animal"
    # original is never mutated
    assert _drafts.get_draft(draft.id).original == TEXT


def test_undo_replays_to_the_prior_state():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    _drafts.record_revision(
        draft.id, instruction="a", selection="quick", span_start=TEXT.index("quick"),
        span_len=5, revised="QUICK", note="", cost={},
    )
    after_one = _drafts.get_draft(draft.id).current
    _drafts.record_revision(
        draft.id, instruction="b", selection="dog", span_start=after_one.index("dog"),
        span_len=3, revised="DOG", note="", cost={},
    )
    assert _drafts.get_draft(draft.id).current == after_one.replace("dog", "DOG", 1)

    back = _drafts.undo_last(draft.id)
    assert back.current == after_one
    assert len(back.revisions) == 1

    back = _drafts.undo_last(draft.id)
    assert back.current == TEXT
    assert back.revisions == []


def test_undo_with_no_revisions_is_a_noop():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    back = _drafts.undo_last(draft.id)
    assert back.current == TEXT
    assert back.revisions == []


# --- the routes -------------------------------------------------------


def test_open_draft_redirects_to_the_editor(client: TestClient):
    resp = client.post(
        "/drafts",
        data={"slug": SLUG, "section": SECTION, "text": TEXT},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    loc = resp.headers["location"]
    assert loc.startswith("/drafts/")
    # re-opening the same result returns the same draft
    again = client.post(
        "/drafts", data={"slug": SLUG, "section": SECTION, "text": TEXT},
        follow_redirects=False,
    )
    assert again.headers["location"] == loc


def test_editor_page_renders_the_current_text(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    body = client.get(f"/drafts/{draft.id}").text
    assert "quick brown fox" in body
    assert "draft-edit.js" in body


def test_revise_returns_a_proposal_without_mutating(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    start = TEXT.index("quick brown")
    resp = client.post(
        f"/drafts/{draft.id}/revise",
        data={
            "selection": "quick brown",
            "span_start": start,
            "span_len": len("quick brown"),
            "instruction": "shout it",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["revised"] == "QUICK BROWN"
    assert data["note"]
    assert data["cost"]["usd"] == 0.0012
    # the draft itself is untouched
    assert _drafts.get_draft(draft.id).current == TEXT
    assert _drafts.get_draft(draft.id).revisions == []


def test_revise_rejects_a_stale_selection(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    resp = client.post(
        f"/drafts/{draft.id}/revise",
        data={"selection": "not there", "span_start": 0, "span_len": 9, "instruction": "x"},
    )
    assert resp.status_code == 409
    assert "out of date" in resp.json()["error"]


def test_revise_requires_an_instruction(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    start = TEXT.index("quick")
    resp = client.post(
        f"/drafts/{draft.id}/revise",
        data={"selection": "quick", "span_start": start, "span_len": 5, "instruction": "  "},
    )
    assert resp.status_code == 422


def test_accept_mutates_and_appends_history(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    start = TEXT.index("quick brown")
    resp = client.post(
        f"/drafts/{draft.id}/accept",
        data={
            "selection": "quick brown",
            "span_start": start,
            "span_len": len("quick brown"),
            "instruction": "shout it",
            "revised": "QUICK BROWN",
            "note": "upper-cased",
            "cost": '{"usd": 0.0012, "input_tokens": 40}',
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["revision_count"] == 1
    assert resp.json()["can_undo"] is True

    stored = _drafts.get_draft(draft.id)
    assert stored.current == TEXT.replace("quick brown", "QUICK BROWN", 1)
    assert stored.revisions[0].note == "upper-cased"
    assert stored.revisions[0].cost["usd"] == 0.0012


def test_accept_then_undo_route_reverts(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    start = TEXT.index("fox")
    client.post(
        f"/drafts/{draft.id}/accept",
        data={
            "selection": "fox", "span_start": start, "span_len": 3,
            "instruction": "shout", "revised": "FOX", "note": "", "cost": "{}",
        },
    )
    assert _drafts.get_draft(draft.id).current != TEXT
    resp = client.post(f"/drafts/{draft.id}/undo")
    assert resp.status_code == 200
    assert resp.json()["revision_count"] == 0
    assert _drafts.get_draft(draft.id).current == TEXT


def test_download_returns_the_current_markdown(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    _drafts.record_revision(
        draft.id, instruction="x", selection="fox", span_start=TEXT.index("fox"),
        span_len=3, revised="FOX", note="", cost={},
    )
    resp = client.get(f"/drafts/{draft.id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text == TEXT.replace("fox", "FOX", 1)


def test_unknown_draft_is_404(client: TestClient):
    assert client.get("/drafts/nope").status_code == 404
    assert client.post("/drafts/nope/undo").status_code == 404
    assert client.get("/drafts/nope/download").status_code == 404


def test_drafts_area_requires_auth():
    guarded = TestClient(create_app(auth_disabled=False))
    resp = guarded.get("/drafts/whatever", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


def test_stub_mode_revise_returns_a_canned_proposal():
    stub = TestClient(create_app(auth_disabled=True, stub_runs=True))
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT)
    start = TEXT.index("quick")
    resp = stub.post(
        f"/drafts/{draft.id}/revise",
        data={"selection": "quick", "span_start": start, "span_len": 5, "instruction": "x"},
    )
    assert resp.status_code == 200
    assert "stub" in resp.json()["note"].lower()
