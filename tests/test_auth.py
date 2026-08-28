"""Login gate and the password hashing."""

from __future__ import annotations

from starlette.testclient import TestClient

from dashboard._auth import hash_password, verify_password
from dashboard.app import create_app
from dashboard.pages import PAGES

A_PAGE = f"/p/{PAGES[0].slug}"


def test_hash_roundtrip() -> None:
    encoded = hash_password("correct horse")
    assert verify_password("correct horse", encoded)
    assert not verify_password("Correct Horse", encoded)
    assert not verify_password("", encoded)
    assert not verify_password("x", "not-a-hash")


def test_pages_redirect_to_login_when_not_authed() -> None:
    client = TestClient(create_app(auth_disabled=False))
    resp = client.get(A_PAGE, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


def test_login_flow(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", hash_password("hunter2"))
    client = TestClient(create_app(auth_disabled=False))

    assert client.post("/login", data={"password": "nope"}, follow_redirects=False).status_code == 401

    good = client.post("/login", data={"password": "hunter2"}, follow_redirects=False)
    assert good.status_code == 303
    assert client.get(A_PAGE).status_code == 200


def test_health_is_public() -> None:
    client = TestClient(create_app(auth_disabled=False))
    assert client.get("/health").json() == {"ok": True}
