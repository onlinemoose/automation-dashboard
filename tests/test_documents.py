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
    a = _documents.create_document("Bio", "Ten years shipping data tools.")
    b = _documents.create_document("Portfolio", "Rebuilt the billing pipeline.")

    assert [d.title for d in _documents.list_documents()] == ["Bio", "Portfolio"]
    assert _documents.get_document(a.id).body == "Ten years shipping data tools."
    assert {d.id for d in _documents.get_documents([a.id, b.id])} == {a.id, b.id}
    assert _documents.get_documents([]) == []

    _documents.update_document(a.id, "Bio", "Twelve years now.")
    assert _documents.get_document(a.id).body == "Twelve years now."

    _documents.delete_document(a.id)
    assert _documents.get_document(a.id) is None
    assert [d.title for d in _documents.list_documents()] == ["Portfolio"]


# --- the CRUD screen -------------------------------------------------------


def test_documents_page_lists_saved_docs(client: TestClient) -> None:
    _documents.create_document("Company context", "They sell to hospitals.")
    body = client.get("/documents").text
    assert "Company context" in body
    assert "They sell to hospitals." in body


def test_new_document_form_renders(client: TestClient) -> None:
    body = client.get("/documents/new").text
    assert 'name="title"' in body and 'name="body"' in body


def test_create_edit_delete_through_the_ui(client: TestClient) -> None:
    assert client.get("/documents/new").status_code == 200

    resp = client.post(
        "/documents/new",
        data={"title": "Bio", "body": "First draft."},
        follow_redirects=False,
    )
    assert resp.status_code == 303 and resp.headers["location"] == "/documents"
    doc = _documents.list_documents()[0]

    edit_form = client.get(f"/documents/{doc.id}").text
    assert "First draft." in edit_form

    resp = client.post(
        f"/documents/{doc.id}",
        data={"title": "Bio", "body": "Second draft."},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _documents.get_document(doc.id).body == "Second draft."

    resp = client.post(f"/documents/{doc.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert _documents.list_documents() == []


def test_create_requires_a_title(client: TestClient) -> None:
    resp = client.post("/documents/new", data={"title": "", "body": "x"})
    assert resp.status_code == 422
    assert "Title is required." in resp.text
    assert _documents.list_documents() == []


def test_edit_unknown_doc_is_404(client: TestClient) -> None:
    assert client.get("/documents/nope").status_code == 404


def test_documents_area_requires_auth() -> None:
    guarded = TestClient(create_app(auth_disabled=False))
    resp = guarded.get("/documents", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


# --- wiring into a writer page ------------------------------------------------


def test_checklist_appears_on_the_writer_page(client: TestClient) -> None:
    _documents.create_document("Bio", "Ten years shipping data tools.")
    body = client.get("/p/cover-letter-writer").text
    assert 'name="background_document_ids"' in body
    assert "Bio" in body


def test_ticked_documents_reach_the_capability_input(monkeypatch) -> None:
    doc = _documents.create_document("Bio", "Ten years shipping data tools.")

    seen: dict[str, object] = {}

    def fake_run(data):
        seen["data"] = data
        return cover_letter_writer.PAGE.example_output

    monkeypatch.setattr(cover_letter_writer.PAGE, "run", fake_run)
    client = TestClient(create_app(auth_disabled=True))

    resp = client.post(
        "/p/cover-letter-writer",
        data={**dict(cover_letter_writer.PAGE.example_form),
              "background_document_ids": doc.id,
              "background_documents": "a one-off note"},
    )
    assert resp.status_code == 200, resp.text
    assert seen["data"].background_documents == [
        "Ten years shipping data tools.",
        "a one-off note",
    ]
