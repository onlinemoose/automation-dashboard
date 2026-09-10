"""Login gate and the password hashing."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from dashboard import _auth
from dashboard._auth import hash_password, verify_password
from dashboard.app import create_app
from dashboard.pages import PAGES

A_PAGE = f"/p/{PAGES[0].slug}"


@pytest.fixture(autouse=True)
def _fresh_auth_backend():
    """`_auth` caches its backend in a module global; drop it around each
    test so the env each one sets is the env it gets. (No conftest here.)"""
    _auth.reset()
    yield
    _auth.reset()


@pytest.fixture
def dev_login(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", hash_password("hunter2"))
    monkeypatch.setenv("DASHBOARD_DEV_EMAIL", "operator@example.com")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)


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


def test_login_flow(dev_login) -> None:
    client = TestClient(create_app(auth_disabled=False))

    bad = client.post(
        "/login",
        data={"email": "operator@example.com", "password": "nope"},
        follow_redirects=False,
    )
    assert bad.status_code == 401

    good = client.post(
        "/login",
        data={"email": "operator@example.com", "password": "hunter2"},
        follow_redirects=False,
    )
    assert good.status_code == 303
    assert client.get(A_PAGE).status_code == 200


def test_login_rejects_the_right_password_under_the_wrong_email(dev_login) -> None:
    client = TestClient(create_app(auth_disabled=False))
    resp = client.post(
        "/login",
        data={"email": "someone-else@example.com", "password": "hunter2"},
        follow_redirects=False,
    )
    assert resp.status_code == 401
    assert client.get(A_PAGE, follow_redirects=False).status_code == 303


def test_login_sets_user_in_session(dev_login) -> None:
    """The session of record now carries the user, not a bare `authed` flag —
    and clearing it signs out again."""
    client = TestClient(create_app(auth_disabled=False))
    client.post(
        "/login",
        data={"email": "operator@example.com", "password": "hunter2"},
        follow_redirects=False,
    )
    assert client.get("/").status_code == 200

    client.get("/logout", follow_redirects=False)
    resp = client.get(A_PAGE, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


def test_topbar_shows_signed_in_email(dev_login) -> None:
    client = TestClient(create_app(auth_disabled=False))
    client.post(
        "/login",
        data={"email": "operator@example.com", "password": "hunter2"},
        follow_redirects=False,
    )
    assert "operator@example.com" in client.get("/").text


def test_health_is_public() -> None:
    client = TestClient(create_app(auth_disabled=False))
    assert client.get("/health").json() == {"ok": True}


# --- setting a password: invite & recovery -----------------------------
# The Supabase happy path (verify_otp -> update_user) needs a live project
# and is verified by hand, like the sign-in path (see test_auth_backend.py).
# Here: the routes exist, are public, and degrade cleanly with no Supabase.


@pytest.fixture
def offline_auth(monkeypatch):
    """No Supabase Auth configured — the invite/recovery flow is unavailable."""
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)


def test_login_page_links_to_forgot_password() -> None:
    client = TestClient(create_app(auth_disabled=False))
    assert 'href="/auth/forgot"' in client.get("/login").text


def test_login_and_forgot_pages_have_no_signup_link(offline_auth) -> None:
    """Invite-only: neither page offers self-serve account creation."""
    client = TestClient(create_app(auth_disabled=False))
    for path in ("/login", "/auth/forgot"):
        text = client.get(path).text.lower()
        assert "sign up" not in text
        assert "create account" not in text
        assert "create an account" not in text


def test_forgot_form_renders(offline_auth) -> None:
    client = TestClient(create_app(auth_disabled=False))
    resp = client.get("/auth/forgot")
    assert resp.status_code == 200
    assert 'name="email"' in resp.text


def test_forgot_submit_is_generic_and_safe_offline(offline_auth) -> None:
    client = TestClient(create_app(auth_disabled=False))
    resp = client.post("/auth/forgot", data={"email": "whoever@example.com"})
    assert resp.status_code == 200
    assert "if that address has an account" in resp.text.lower()


def test_set_password_form_rejects_an_unknown_type(offline_auth) -> None:
    client = TestClient(create_app(auth_disabled=False))
    resp = client.get(
        "/auth/set-password", params={"type": "bogus", "token_hash": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_set_password_form_shows_unavailable_offline(offline_auth) -> None:
    client = TestClient(create_app(auth_disabled=False))
    resp = client.get(
        "/auth/set-password", params={"type": "recovery", "token_hash": "x"}
    )
    assert resp.status_code == 200
    # The "unavailable" branch: an explanation and a way back, no form.
    assert 'type="password"' not in resp.text
    assert 'action="/auth/set-password"' not in resp.text
    assert 'href="/login"' in resp.text


def test_set_password_submit_offline_does_not_error(offline_auth) -> None:
    client = TestClient(create_app(auth_disabled=False))
    resp = client.post(
        "/auth/set-password",
        data={"type": "invite", "token_hash": "x", "password": "a-good-password"},
    )
    assert resp.status_code == 400
    assert 'type="password"' not in resp.text
    assert 'action="/auth/set-password"' not in resp.text
