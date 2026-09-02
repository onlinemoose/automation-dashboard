"""The Background documents area: the app's own store, its CRUD screen, and
the checklist that folds saved notes into a writer page's `background_documents`.

The store falls back to an in-process dict when Supabase isn't configured
(no env vars in the test run), so nothing here needs a network.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from dashboard import _documents
from dashboard.app import create_app
from dashboard.pages import cover_letter_writer

# Must match `create_app`'s default `as_user` — the id the app scopes by
# when auth is disabled.
USER = "test-user"


@pytest.fixture(autouse=True)
def fresh_store():
    _documents.reset()
    yield
    _documents.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


# --- the store ---------------------------------------------------------------


def test_store_crud_roundtrip() -> None:
    a = _documents.create_document("Bio", "Ten years shipping data tools.", USER)
    b = _documents.create_document("Portfolio", "Rebuilt the billing pipeline.", USER)

    assert [d.title for d in _documents.list_documents(USER)] == ["Bio", "Portfolio"]
    assert _documents.get_document(a.id, USER).body == "Ten years shipping data tools."
    assert {d.id for d in _documents.get_documents([a.id, b.id], USER)} == {a.id, b.id}
    assert _documents.get_documents([], USER) == []

    _documents.update_document(a.id, "Bio", "Twelve years now.", USER)
    assert _documents.get_document(a.id, USER).body == "Twelve years now."

    _documents.delete_document(a.id, USER)
    assert _documents.get_document(a.id, USER) is None
    assert [d.title for d in _documents.list_documents(USER)] == ["Portfolio"]


def test_is_cv_flag_roundtrips_and_filters_the_listing() -> None:
    cv = _documents.create_document("Priya CV", "cv body", USER, is_cv=True)
    note = _documents.create_document("Portfolio", "project write-ups", USER)

    assert _documents.get_document(cv.id, USER).is_cv is True
    assert _documents.get_document(note.id, USER).is_cv is False  # the default

    assert [d.title for d in _documents.list_documents(USER)] == ["Portfolio", "Priya CV"]
    assert [d.title for d in _documents.list_documents(USER, is_cv=True)] == ["Priya CV"]
    assert [d.title for d in _documents.list_documents(USER, is_cv=False)] == ["Portfolio"]

    # The flag moves with an update.
    _documents.update_document(note.id, "Portfolio", "project write-ups", USER, is_cv=True)
    assert _documents.get_document(note.id, USER).is_cv is True
    assert {d.title for d in _documents.list_documents(USER, is_cv=True)} == {
        "Priya CV",
        "Portfolio",
    }


def test_documents_are_scoped_to_the_user() -> None:
    """A row created by one user is invisible to another — not merely
    unlisted, but unreadable, unwritable and undeletable."""
    mine = _documents.create_document("Bio", "Mine.", "user-a")

    assert _documents.list_documents("user-b") == []
    assert _documents.get_document(mine.id, "user-b") is None
    assert _documents.get_documents([mine.id], "user-b") == []
    assert _documents.update_document(mine.id, "Hijacked", "Theirs.", "user-b") is None
    _documents.delete_document(mine.id, "user-b")

    # A's row is untouched by any of that.
    still = _documents.get_document(mine.id, "user-a")
    assert still is not None
    assert (still.title, still.body) == ("Bio", "Mine.")
    assert still.user_id == "user-a"


def test_the_documents_page_only_lists_the_callers_docs() -> None:
    a = TestClient(create_app(auth_disabled=True, as_user="user-a"))
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))

    a.post("/documents/new", data={"title": "Alpha note", "body": "Private."})

    assert "Alpha note" in a.get("/documents").text
    assert "Alpha note" not in b.get("/documents").text


def test_another_users_document_is_404_over_http() -> None:
    a = TestClient(create_app(auth_disabled=True, as_user="user-a"))
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))
    a.post("/documents/new", data={"title": "Alpha note", "body": "Private."})
    doc = _documents.list_documents("user-a")[0]

    assert b.get(f"/documents/{doc.id}").status_code == 404
    assert b.post(f"/documents/{doc.id}", data={"title": "X", "body": "Y"}).status_code == 404
    # Delete is a no-op rather than a 404 (it redirects either way) — what
    # matters is that A's row survives it.
    b.post(f"/documents/{doc.id}/delete", follow_redirects=False)
    assert _documents.get_document(doc.id, "user-a") is not None


def test_checklist_only_lists_the_callers_docs() -> None:
    _documents.create_document("Alpha bio", "Private.", "user-a")
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))
    body = b.get("/p/cover-letter-writer?example=1").text
    assert 'name="background_document_ids"' in body
    assert "Alpha bio" not in body


def test_another_users_document_id_cannot_be_smuggled_into_a_run(monkeypatch) -> None:
    """Ticking a foreign id in the checklist resolves to nothing, rather
    than folding that user's text into the capability call."""
    foreign = _documents.create_document("Alpha bio", "A's private text.", "user-a")

    seen: dict[str, object] = {}

    def fake_run(data, **_):
        seen["data"] = data
        return cover_letter_writer.PAGE.example_output

    monkeypatch.setattr(cover_letter_writer.PAGE, "run", fake_run)
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))

    resp = b.post(
        "/p/cover-letter-writer",
        data={**dict(cover_letter_writer.PAGE.example_form),
              "background_document_ids": foreign.id,
              "additional_context": "b's own note"},
    )
    assert resp.status_code == 200, resp.text
    assert seen["data"].background_documents == ["b's own note"]


# --- the CRUD screen -------------------------------------------------------


def test_documents_page_lists_saved_docs(client: TestClient) -> None:
    _documents.create_document("Company context", "They sell to hospitals.", USER)
    body = client.get("/documents").text
    assert "Company context" in body
    assert "They sell to hospitals." in body


def test_documents_delete_is_an_icon_button(client: TestClient) -> None:
    doc = _documents.create_document("Company context", "They sell to hospitals.", USER)
    body = client.get("/documents").text
    assert f'action="/documents/{doc.id}/delete"' in body
    assert 'class="iconbtn iconbtn--danger"' in body
    assert 'aria-label="Delete document"' in body


def test_new_document_form_renders(client: TestClient) -> None:
    body = client.get("/documents/new").text
    assert 'name="title"' in body and 'name="body"' in body
    assert 'name="is_cv"' in body  # the "This document is a CV" toggle


def test_new_document_defaults_to_a_background_note(client: TestClient) -> None:
    client.post("/documents/new", data={"title": "Bio", "body": "x"}, follow_redirects=False)
    assert _documents.list_documents(USER)[0].is_cv is False


def test_a_new_document_can_be_marked_a_cv(client: TestClient) -> None:
    client.post(
        "/documents/new",
        data={"title": "My CV", "body": "x", "is_cv": "on"},
        follow_redirects=False,
    )
    assert _documents.list_documents(USER)[0].is_cv is True


def test_editing_toggles_the_cv_flag(client: TestClient) -> None:
    doc = _documents.create_document("My CV", "x", USER, is_cv=True)

    edit_form = client.get(f"/documents/{doc.id}").text
    assert 'name="is_cv"' in edit_form and "checked" in edit_form

    # Submitting the form with the box unticked (the field is simply absent).
    client.post(f"/documents/{doc.id}", data={"title": "My CV", "body": "x"},
                follow_redirects=False)
    assert _documents.get_document(doc.id, USER).is_cv is False


def test_documents_list_groups_cvs_and_notes_under_separate_headings(client: TestClient) -> None:
    _documents.create_document("Priya CV", "cv body", USER, is_cv=True)
    _documents.create_document("Portfolio", "project notes", USER)
    body = client.get("/documents").text
    assert "<h2>CVs</h2>" in body and "<h2>Background documents</h2>" in body
    assert body.index("<h2>CVs</h2>") < body.index("Priya CV") < body.index("<h2>Background documents</h2>")
    assert body.index("<h2>Background documents</h2>") < body.index("Portfolio")


def test_create_edit_delete_through_the_ui(client: TestClient) -> None:
    assert client.get("/documents/new").status_code == 200

    resp = client.post(
        "/documents/new",
        data={"title": "Bio", "body": "First draft."},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/documents"
    doc = _documents.list_documents(USER)[0]

    edit_form = client.get(f"/documents/{doc.id}").text
    assert "First draft." in edit_form

    resp = client.post(
        f"/documents/{doc.id}",
        data={"title": "Bio", "body": "Second draft."},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _documents.get_document(doc.id, USER).body == "Second draft."

    resp = client.post(f"/documents/{doc.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert _documents.list_documents(USER) == []


def test_create_requires_a_title(client: TestClient) -> None:
    resp = client.post("/documents/new", data={"title": "", "body": "x"})
    assert resp.status_code == 422
    assert "Title is required." in resp.text
    assert _documents.list_documents(USER) == []


def test_edit_unknown_doc_is_404(client: TestClient) -> None:
    assert client.get("/documents/nope").status_code == 404


def test_documents_area_requires_auth() -> None:
    guarded = TestClient(create_app(auth_disabled=False))
    resp = guarded.get("/documents", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


# --- wiring into a writer page ------------------------------------------------


def test_checklist_appears_on_the_writer_page(client: TestClient) -> None:
    _documents.create_document("Bio", "Ten years shipping data tools.", USER)
    body = client.get("/p/cover-letter-writer?example=1").text
    assert 'name="background_document_ids"' in body
    assert "Bio" in body


def test_free_text_note_field_is_named_for_what_it_is(client: TestClient) -> None:
    for slug in ("cover-letter-writer", "cv-writer"):
        body = client.get(f"/p/{slug}?example=1").text
        assert 'name="additional_context"' in body
        # The old name collided with the contract argument; it's gone.
        assert 'name="background_documents"' not in body


def test_ticked_documents_reach_the_capability_input(monkeypatch) -> None:
    doc = _documents.create_document("Bio", "Ten years shipping data tools.", USER)

    seen: dict[str, object] = {}

    def fake_run(data, **_):
        seen["data"] = data
        return cover_letter_writer.PAGE.example_output

    monkeypatch.setattr(cover_letter_writer.PAGE, "run", fake_run)
    client = TestClient(create_app(auth_disabled=True))

    resp = client.post(
        "/p/cover-letter-writer",
        data={**dict(cover_letter_writer.PAGE.example_form),
              "background_document_ids": doc.id,
              "additional_context": "a one-off note"},
    )
    assert resp.status_code == 200, resp.text
    assert seen["data"].background_documents == [
        "Ten years shipping data tools.",
        "a one-off note",
    ]


# --- the CV document picker -------------------------------------------------


def test_cv_picker_replaces_the_cv_textarea_on_both_writer_pages(client: TestClient) -> None:
    _documents.create_document("My CV", "Priya Nair — infra engineer.", USER, is_cv=True)
    for slug in ("cover-letter-writer", "cv-writer"):
        body = client.get(f"/p/{slug}?example=1").text
        assert 'name="cv_document_id"' in body  # the picker
        assert "My CV" in body  # listing the caller's CVs
        assert 'name="cv"' not in body  # the free-text box is gone


def test_a_cv_is_offered_only_in_the_picker_and_a_note_only_in_the_checklist(
    client: TestClient,
) -> None:
    _documents.create_document("Priya CV", "CV BODY", USER, is_cv=True)
    _documents.create_document("Portfolio", "PROJECT NOTES", USER)  # a background note

    for slug in ("cover-letter-writer", "cv-writer"):
        body = client.get(f"/p/{slug}?example=1").text
        # The checklist region begins at its hidden input; nothing that
        # names a document title comes after it in these forms.
        before, checklist = body.split('name="background_document_ids"', 1)
        assert "Priya CV" in before and "Priya CV" not in checklist  # picker only
        assert "Portfolio" in checklist and "Portfolio" not in before  # checklist only


def test_picked_cv_document_reaches_the_capability(monkeypatch) -> None:
    doc = _documents.create_document("My CV", "PRIYA NAIR CV BODY", USER, is_cv=True)

    seen: dict[str, object] = {}

    def fake_run(data, **_):
        seen["data"] = data
        return cover_letter_writer.PAGE.example_output

    monkeypatch.setattr(cover_letter_writer.PAGE, "run", fake_run)
    client = TestClient(create_app(auth_disabled=True))

    form = dict(cover_letter_writer.PAGE.example_form)
    form.pop("cv", None)  # prove the CV comes from the picked document
    resp = client.post(
        "/p/cover-letter-writer",
        data={**form, "cv_document_id": doc.id},
    )
    assert resp.status_code == 200, resp.text
    assert seen["data"].cv == "PRIYA NAIR CV BODY"


def test_writer_run_requires_a_cv_document(client: TestClient) -> None:
    resp = client.post(
        "/p/cover-letter-writer",
        data={"job_posting": "A posting to satisfy the job side.",
              "cv_document_id": "", "cv": ""},
    )
    assert resp.status_code == 422
    assert "Load a saved CV." in resp.text


def test_a_foreign_cv_document_cannot_be_smuggled_into_a_run() -> None:
    foreign = _documents.create_document("A's CV", "SECRET CV OF USER A", "user-a")
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))
    resp = b.post(
        "/p/cover-letter-writer",
        data={"job_posting": "A posting.", "cv_document_id": foreign.id, "cv": ""},
    )
    assert resp.status_code == 422  # not resolved -> required error, no leak
    assert "SECRET CV OF USER A" not in resp.text
