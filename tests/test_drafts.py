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

from dashboard import _drafts, _jobs
from dashboard.app import create_app

# Must match `create_app`'s default `as_user` — the id the app scopes by
# when auth is disabled.
USER = "test-user"

SLUG = "cover-letter-writer"
SECTION = "cover-letter"
TEXT = "The quick brown fox jumps over the lazy dog.\n\nA second paragraph follows here."


@pytest.fixture(autouse=True)
def fresh_store():
    _drafts.reset()
    _jobs.reset()
    yield
    _drafts.reset()
    _jobs.reset()


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
    a = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    b = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    assert a.id == b.id
    assert a.original == a.current == TEXT
    assert a.revisions == []

    # different text -> different draft
    c = _drafts.create_or_get_draft(SLUG, SECTION, TEXT + " more", USER)
    assert c.id != a.id
    # different section -> different draft
    d = _drafts.create_or_get_draft(SLUG, "targeting-note", TEXT, USER)
    assert d.id != a.id
    # different user, same (slug, section, text) -> a different draft.
    # Miss the owner in the lookup and B lands on A's draft, revisions
    # and all.
    e = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, "someone-else")
    assert e.id != a.id
    assert e.user_id == "someone-else"


def test_create_or_get_stamps_and_backfills_the_job_post_link():
    # first open, outside any job post
    a = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    assert a.job_post_id == ""

    # re-opening the same result from a job post backfills the link
    # (same draft — job_post_id is not part of the dedupe key)
    b = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER, "job-123")
    assert b.id == a.id
    assert b.job_post_id == "job-123"
    assert _drafts.get_draft(a.id, USER).job_post_id == "job-123"

    # an already-linked draft keeps its post — a later bare open can't clear it
    c = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    assert c.id == a.id and c.job_post_id == "job-123"

    # a fresh result created from a job post carries it from the start
    d = _drafts.create_or_get_draft(SLUG, SECTION, TEXT + " more", USER, "job-999")
    assert d.id != a.id and d.job_post_id == "job-999"


def test_drafts_are_scoped_to_the_user():
    """Another user's draft is unreadable and unwritable at the store level."""
    mine = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, "user-a")

    assert _drafts.get_draft(mine.id, "user-b") is None
    assert _drafts.undo_last(mine.id, "user-b") is None
    assert _drafts.record_revision(
        mine.id, "user-b",
        instruction="hijack", selection="fox", span_start=TEXT.index("fox"),
        span_len=3, revised="OWNED", note="", cost={},
    ) is None

    still = _drafts.get_draft(mine.id, "user-a")
    assert still is not None
    assert still.current == TEXT
    assert still.revisions == []


def test_another_users_draft_is_404_over_http():
    """Each draft route already 404s on a None fetch, so scoping the fetch
    gives 404-not-403 for free — no separate forbidden path."""
    mine = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, "user-a")
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))

    assert b.get(f"/drafts/{mine.id}").status_code == 404
    assert b.get(f"/drafts/{mine.id}/download").status_code == 404
    assert b.post(f"/drafts/{mine.id}/undo").status_code == 404
    assert b.post(
        f"/drafts/{mine.id}/revise",
        data={"selection": "fox", "instruction": "shout",
              "span_start": TEXT.index("fox"), "span_len": 3},
    ).status_code == 404
    assert b.post(
        f"/drafts/{mine.id}/accept",
        data={"selection": "fox", "revised": "OWNED", "instruction": "shout",
              "note": "", "span_start": TEXT.index("fox"), "span_len": 3, "cost": "{}"},
    ).status_code == 404

    still = _drafts.get_draft(mine.id, "user-a")
    assert still.current == TEXT
    assert still.revisions == []


def test_record_revision_appends_and_resplices():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    updated = _drafts.record_revision(
        draft.id, USER,
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
    assert _drafts.get_draft(draft.id, USER).original == TEXT


def test_undo_replays_to_the_prior_state():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    _drafts.record_revision(
        draft.id, USER, instruction="a", selection="quick", span_start=TEXT.index("quick"),
        span_len=5, revised="QUICK", note="", cost={},
    )
    after_one = _drafts.get_draft(draft.id, USER).current
    _drafts.record_revision(
        draft.id, USER, instruction="b", selection="dog", span_start=after_one.index("dog"),
        span_len=3, revised="DOG", note="", cost={},
    )
    assert _drafts.get_draft(draft.id, USER).current == after_one.replace("dog", "DOG", 1)

    back = _drafts.undo_last(draft.id, USER)
    assert back.current == after_one
    assert len(back.revisions) == 1

    back = _drafts.undo_last(draft.id, USER)
    assert back.current == TEXT
    assert back.revisions == []


def test_undo_with_no_revisions_is_a_noop():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    back = _drafts.undo_last(draft.id, USER)
    assert back.current == TEXT
    assert back.revisions == []


def test_record_manual_edit_replaces_current_and_is_undoable():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    new = "A hand-written replacement.\n\nWith two paragraphs."
    updated = _drafts.record_manual_edit(draft.id, USER, text=new)
    assert updated.current == new
    assert len(updated.revisions) == 1
    assert updated.revisions[0].instruction == _drafts.MANUAL_EDIT
    assert _drafts.get_draft(draft.id, USER).original == TEXT  # never mutated

    back = _drafts.undo_last(draft.id, USER)
    assert back.current == TEXT
    assert back.revisions == []


def test_manual_edit_layers_on_and_off_a_span_revision():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    _drafts.record_revision(
        draft.id, USER, instruction="shout", selection="fox",
        span_start=TEXT.index("fox"), span_len=3, revised="FOX", note="", cost={},
    )
    after_span = _drafts.get_draft(draft.id, USER).current
    _drafts.record_manual_edit(draft.id, USER, text=after_span + "\n\nPS.")
    assert _drafts.get_draft(draft.id, USER).current == after_span + "\n\nPS."

    back = _drafts.undo_last(draft.id, USER)  # drop the manual edit
    assert back.current == after_span
    assert len(back.revisions) == 1


def test_manual_edit_is_a_noop_when_text_is_unchanged():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    same = _drafts.record_manual_edit(draft.id, USER, text=TEXT)
    assert same.revisions == []


def test_manual_edit_normalises_crlf():
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    updated = _drafts.record_manual_edit(draft.id, USER, text="line one\r\nline two")
    assert updated.current == "line one\nline two"


def test_manual_edit_of_a_foreign_draft_is_none():
    mine = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, "user-a")
    assert _drafts.record_manual_edit(mine.id, "user-b", text="hijack") is None
    assert _drafts.get_draft(mine.id, "user-a").current == TEXT


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
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    body = client.get(f"/drafts/{draft.id}").text
    assert "quick brown fox" in body
    assert "draft-edit.js" in body


def test_editor_page_lets_the_doc_be_edited_directly(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    body = client.get(f"/drafts/{draft.id}").text
    # the draft <pre> is directly editable — no separate edit mode/button
    assert '<pre class="draft__doc" id="draft-doc" contenteditable="true"' in body
    assert 'id="draft-edit-btn"' not in body


def test_revise_returns_a_proposal_without_mutating(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
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
    assert _drafts.get_draft(draft.id, USER).current == TEXT
    assert _drafts.get_draft(draft.id, USER).revisions == []


def test_revise_rejects_a_selection_that_is_gone(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    resp = client.post(
        f"/drafts/{draft.id}/revise",
        data={"selection": "not there", "span_start": 0, "span_len": 9, "instruction": "x"},
    )
    assert resp.status_code == 409
    assert "reselect" in resp.json()["error"]


def test_revise_recovers_when_offsets_are_off_but_the_text_is_present(client: TestClient):
    # A <pre> can shift character offsets (leading newline, CRLF). If the
    # selection text still occurs exactly once, the route locates it.
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    resp = client.post(
        f"/drafts/{draft.id}/revise",
        data={
            "selection": "quick brown",
            "span_start": 0,  # wrong — real offset is 4
            "span_len": len("quick brown"),
            "instruction": "shout it",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["span_start"] == TEXT.index("quick brown")
    assert body["revised"] == "QUICK BROWN"


def test_revise_requires_an_instruction(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    start = TEXT.index("quick")
    resp = client.post(
        f"/drafts/{draft.id}/revise",
        data={"selection": "quick", "span_start": start, "span_len": 5, "instruction": "  "},
    )
    assert resp.status_code == 422


def test_accept_mutates_and_appends_history(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
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

    stored = _drafts.get_draft(draft.id, USER)
    assert stored.current == TEXT.replace("quick brown", "QUICK BROWN", 1)
    assert stored.revisions[0].note == "upper-cased"
    assert stored.revisions[0].cost["usd"] == 0.0012


def test_accept_then_undo_route_reverts(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    start = TEXT.index("fox")
    client.post(
        f"/drafts/{draft.id}/accept",
        data={
            "selection": "fox", "span_start": start, "span_len": 3,
            "instruction": "shout", "revised": "FOX", "note": "", "cost": "{}",
        },
    )
    assert _drafts.get_draft(draft.id, USER).current != TEXT
    resp = client.post(f"/drafts/{draft.id}/undo")
    assert resp.status_code == 200
    assert resp.json()["revision_count"] == 0
    assert _drafts.get_draft(draft.id, USER).current == TEXT


def test_manual_edit_route_replaces_and_records(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    resp = client.post(f"/drafts/{draft.id}/edit", data={"text": "Rewritten by hand."})
    assert resp.status_code == 200, resp.text
    assert resp.json()["current"] == "Rewritten by hand."
    assert resp.json()["revision_count"] == 1
    assert resp.json()["can_undo"] is True
    assert _drafts.get_draft(draft.id, USER).current == "Rewritten by hand."


def test_manual_edit_route_then_undo_reverts(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    client.post(f"/drafts/{draft.id}/edit", data={"text": "hand edit"})
    resp = client.post(f"/drafts/{draft.id}/undo")
    assert resp.json()["revision_count"] == 0
    assert _drafts.get_draft(draft.id, USER).current == TEXT


def test_manual_edit_route_rejects_an_empty_draft(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    resp = client.post(f"/drafts/{draft.id}/edit", data={"text": "   "})
    assert resp.status_code == 422
    assert _drafts.get_draft(draft.id, USER).current == TEXT


def test_manual_edit_route_unknown_draft_is_404(client: TestClient):
    assert client.post("/drafts/nope/edit", data={"text": "x"}).status_code == 404


def test_download_returns_the_current_markdown(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    _drafts.record_revision(
        draft.id, USER, instruction="x", selection="fox", span_start=TEXT.index("fox"),
        span_len=3, revised="FOX", note="", cost={},
    )
    resp = client.get(f"/drafts/{draft.id}/download")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text == TEXT.replace("fox", "FOX", 1)


# --- save to job post ----------------------------------------------

CL_ORIGINAL = "Dear hiring team,\n\nI am the original letter.\n\nRegards."


def _job_with_saved_letter(user_id: str = USER):
    """A job post carrying a saved cover-letter result, the way the writer
    page leaves it after a run against that post."""
    job = _jobs.create_job_post("Acme — Lead", "the posting text", user_id)
    _jobs.update_job_post(
        job.id, user_id,
        cover_letter={
            "sections": [
                {"heading": "Cover letter", "markdown": CL_ORIGINAL, "editable": True},
                {"heading": "What it targeted", "markdown": "a note", "editable": False},
            ],
            "meta": None,
            "saved_at": "2026-09-02T00:00:00+00:00",
        },
    )
    return job


def test_open_draft_carries_the_job_post_id(client: TestClient):
    resp = client.post(
        "/drafts",
        data={"slug": SLUG, "section": SECTION, "text": TEXT, "job_post_id": "job-7"},
        follow_redirects=False,
    )
    draft_id = resp.headers["location"].removeprefix("/drafts/")
    assert _drafts.get_draft(draft_id, USER).job_post_id == "job-7"
    # the editor now offers "Save to job post"
    body = client.get(f"/drafts/{draft_id}").text
    assert f'action="/drafts/{draft_id}/save"' in body


def test_no_save_button_without_a_job_post(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    assert 'id="draft-save-form"' not in client.get(f"/drafts/{draft.id}").text


def test_save_writes_the_edit_into_the_job_post_slot_and_redirects(client: TestClient):
    job = _job_with_saved_letter()
    draft = _drafts.create_or_get_draft(SLUG, SECTION, CL_ORIGINAL, USER, job.id)
    _drafts.record_manual_edit(draft.id, USER, text="A rewritten cover letter body.")

    resp = client.post(f"/drafts/{draft.id}/save", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/p/{SLUG}?job_post_id={job.id}"

    saved = _jobs.get_job_post(job.id, USER).cover_letter
    bodies = {s["heading"]: s["markdown"] for s in saved["sections"]}
    assert bodies["Cover letter"] == "A rewritten cover letter body."
    assert bodies["What it targeted"] == "a note"  # the read-only section is untouched


def test_saved_edit_shows_on_the_writer_page(client: TestClient):
    job = _job_with_saved_letter()
    draft = _drafts.create_or_get_draft(SLUG, SECTION, CL_ORIGINAL, USER, job.id)
    _drafts.record_manual_edit(draft.id, USER, text="Edited letter that should now render.")
    client.post(f"/drafts/{draft.id}/save", follow_redirects=False)

    body = client.get(f"/p/{SLUG}?job_post_id={job.id}").text
    assert "Edited letter that should now render." in body
    assert "I am the original letter." not in body


def test_save_builds_a_slot_when_the_job_post_has_no_saved_result(client: TestClient):
    job = _jobs.create_job_post("Acme — Lead", "posting", USER)  # writer never ran
    assert _jobs.get_job_post(job.id, USER).cover_letter is None
    draft = _drafts.create_or_get_draft(SLUG, SECTION, CL_ORIGINAL, USER, job.id)
    _drafts.record_manual_edit(draft.id, USER, text="From an unrun job post.")

    resp = client.post(f"/drafts/{draft.id}/save", follow_redirects=False)
    assert resp.status_code == 303
    saved = _jobs.get_job_post(job.id, USER).cover_letter
    assert saved["sections"][0]["heading"] == "Cover letter"
    assert saved["sections"][0]["markdown"] == "From an unrun job post."


def test_save_on_a_draft_with_no_job_post_is_400(client: TestClient):
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    resp = client.post(f"/drafts/{draft.id}/save", follow_redirects=False)
    assert resp.status_code == 400


def test_save_of_a_foreign_draft_is_404():
    job = _jobs.create_job_post("Acme", "posting", "user-a")
    mine = _drafts.create_or_get_draft(SLUG, SECTION, CL_ORIGINAL, "user-a", job.id)
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))
    assert b.post(f"/drafts/{mine.id}/save", follow_redirects=False).status_code == 404
    # user-a's job post is left as it was
    assert _jobs.get_job_post(job.id, "user-a").cover_letter is None


def test_unknown_draft_is_404(client: TestClient):
    assert client.get("/drafts/nope").status_code == 404
    assert client.post("/drafts/nope/undo").status_code == 404
    assert client.get("/drafts/nope/download").status_code == 404
    assert client.post("/drafts/nope/save").status_code == 404


def test_drafts_area_requires_auth():
    guarded = TestClient(create_app(auth_disabled=False))
    resp = guarded.get("/drafts/whatever", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


def test_stub_mode_revise_returns_a_canned_proposal():
    stub = TestClient(create_app(auth_disabled=True, stub_runs=True))
    draft = _drafts.create_or_get_draft(SLUG, SECTION, TEXT, USER)
    start = TEXT.index("quick")
    resp = stub.post(
        f"/drafts/{draft.id}/revise",
        data={"selection": "quick", "span_start": start, "span_len": 5, "instruction": "x"},
    )
    assert resp.status_code == 200
    assert "stub" in resp.json()["note"].lower()
