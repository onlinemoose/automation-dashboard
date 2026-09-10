"""Per-user area access control (docs/ACCESS.md)."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from dashboard import _access, _auth
from dashboard._auth import AuthedUser, areas_from_metadata, hash_password
from dashboard.app import create_app


def test_areas_from_metadata() -> None:
    assert areas_from_metadata({"areas": ["job_application"]}) == ("job_application",)
    assert areas_from_metadata({}) is None
    assert areas_from_metadata(None) is None
    assert areas_from_metadata({"areas": None}) is None
    assert areas_from_metadata({"areas": []}) == ()
    assert areas_from_metadata({"areas": "job_application"}) == ("job_application",)


def test_predicates() -> None:
    unrestricted = AuthedUser(id="u1", email="u1@example.com", areas=None)
    none_granted = AuthedUser(id="u2", email="u2@example.com", areas=())
    job_only = AuthedUser(id="u3", email="u3@example.com", areas=("job_application",))

    assert _access.can_access_path(unrestricted, "/jobs")
    assert _access.can_access_path(unrestricted, "/content")
    assert not _access.can_access_path(none_granted, "/jobs")
    assert not _access.can_access_path(none_granted, "/content")
    assert _access.can_access_path(job_only, "/jobs")
    assert not _access.can_access_path(job_only, "/content")

    assert _access.can_access_slug(job_only, "cv-writer")
    assert not _access.can_access_slug(job_only, "content-creation-team")

    assert len(_access.visible_areas(unrestricted)) == 2
    assert len(_access.visible_areas(none_granted)) == 0
    assert [a.key for a in _access.visible_areas(job_only)] == ["job_application"]

    # Shell paths and unknown paths belong to no area, so they're always allowed.
    assert _access.area_for_path("/") is None
    assert _access.area_for_path("/does-not-exist") is None
    assert _access.can_access_path(none_granted, "/")
    assert _access.can_access_path(none_granted, "/health")


def test_unlisted_sees_both() -> None:
    client = TestClient(create_app(auth_disabled=True, as_areas=None))
    body = client.get("/").text
    assert "Job Application Co-Pilot" in body
    assert "Content Creation Team" in body
    assert client.get("/content").status_code == 200
    assert client.get("/jobs").status_code == 200
    assert client.get("/p/content-creation-team?example=1").status_code == 200


def test_denied_area_hidden_and_404() -> None:
    client = TestClient(
        create_app(auth_disabled=True, as_areas=("job_application",))
    )
    body = client.get("/").text
    assert "Job Application Co-Pilot" in body
    assert "Content Creation Team" not in body
    assert "/content" not in body

    assert client.get("/content").status_code == 404
    assert client.get("/content/new").status_code == 404
    assert client.post("/content/x").status_code == 404
    assert client.get("/p/content-creation-team").status_code == 404
    assert client.post("/p/content-creation-team").status_code == 404

    assert client.get("/jobs").status_code == 200
    assert client.get("/p/cv-writer?example=1").status_code == 200


def test_mirror_content_only() -> None:
    client = TestClient(
        create_app(auth_disabled=True, as_areas=("content_creation_team",))
    )
    assert client.get("/jobs").status_code == 404
    assert client.get("/documents").status_code == 404
    assert client.post("/drafts").status_code == 404
    assert client.get("/p/cv-writer?example=1").status_code == 404

    assert client.get("/content").status_code == 200
    assert client.get("/p/content-creation-team?example=1").status_code == 200

    body = client.get("/").text
    assert "Content Creation Team" in body
    assert "Job Application Co-Pilot" not in body


def test_empty_grants() -> None:
    client = TestClient(create_app(auth_disabled=True, as_areas=()))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Job Application Co-Pilot" not in resp.text
    assert "Content Creation Team" not in resp.text
    assert '<ul class="pagelist">' in resp.text

    assert client.get("/content").status_code == 404
    assert client.get("/jobs").status_code == 404
    assert client.get("/health").status_code == 200
    assert client.get("/login").status_code == 200


def test_unknown_slug_still_404() -> None:
    client = TestClient(
        create_app(auth_disabled=True, as_areas=("job_application",))
    )
    assert client.get("/p/does-not-exist").status_code == 404


@pytest.fixture(autouse=True)
def _fresh_auth_backend():
    _auth.reset()
    yield
    _auth.reset()


def test_offline_login_grants(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", hash_password("hunter2"))
    monkeypatch.setenv("DASHBOARD_DEV_EMAIL", "operator@example.com")
    monkeypatch.setenv("DASHBOARD_DEV_AREAS", "job_application")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)

    client = TestClient(create_app(auth_disabled=False))
    client.post(
        "/login",
        data={"email": "operator@example.com", "password": "hunter2"},
        follow_redirects=False,
    )
    assert client.get("/content").status_code == 404
    assert client.get("/jobs").status_code == 200
