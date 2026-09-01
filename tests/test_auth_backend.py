"""The auth backend and the `current_user` helpers (`dashboard/_auth.py`).

Only the offline backend is exercised here — the Supabase path needs a
live project and is verified by hand (docs/USER_SCOPING.md).
"""

from __future__ import annotations

import pytest

from dashboard import _auth
from dashboard._auth import AuthedUser, hash_password


@pytest.fixture(autouse=True)
def _fresh_backend():
    """The backend is a process-wide singleton; drop it around each test so
    the env each one sets is the env it gets."""
    _auth.reset()
    yield
    _auth.reset()


@pytest.fixture
def dev_login(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", hash_password("hunter2"))
    monkeypatch.setenv("DASHBOARD_DEV_EMAIL", "operator@example.com")
    # Make sure a real .env in the environment can't route us at Supabase.
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)


class _FakeState:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


class _FakeApp:
    def __init__(self, **kw) -> None:
        self.state = _FakeState(**kw)


class _FakeRequest:
    """Just enough of a Starlette request for `current_user`."""

    def __init__(self, session: dict | None = None, **app_state) -> None:
        self.app = _FakeApp(**app_state)
        self.session = session if session is not None else {}


# --- the offline backend --------------------------------------------------


def test_offline_sign_in_accepts_the_configured_operator(dev_login) -> None:
    user = _auth.sign_in("operator@example.com", "hunter2")
    assert user == AuthedUser(id="test-user", email="operator@example.com")


def test_offline_sign_in_matches_the_email_case_insensitively(dev_login) -> None:
    assert _auth.sign_in("Operator@Example.COM", "hunter2") is not None


def test_offline_sign_in_rejects_a_wrong_password(dev_login) -> None:
    assert _auth.sign_in("operator@example.com", "nope") is None


def test_offline_sign_in_rejects_an_unknown_email(dev_login) -> None:
    assert _auth.sign_in("someone-else@example.com", "hunter2") is None


def test_offline_sign_in_rejects_everything_when_no_hash_is_set(monkeypatch) -> None:
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", "")
    monkeypatch.setenv("DASHBOARD_DEV_EMAIL", "operator@example.com")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    assert _auth.sign_in("operator@example.com", "hunter2") is None
    assert _auth.sign_in("operator@example.com", "") is None


def test_the_backend_reads_its_config_fresh_each_call(monkeypatch) -> None:
    """The singleton is cached, so `sign_in` must not have snapshotted the
    environment at construction time."""
    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", hash_password("first"))
    monkeypatch.setenv("DASHBOARD_DEV_EMAIL", "operator@example.com")
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    assert _auth.sign_in("operator@example.com", "first") is not None

    monkeypatch.setenv("DASHBOARD_PASSWORD_HASH", hash_password("second"))
    monkeypatch.setenv("DASHBOARD_DEV_EMAIL", "someone@example.com")
    assert _auth.sign_in("operator@example.com", "first") is None
    assert _auth.sign_in("someone@example.com", "second") is not None


# --- current_user / current_user_id ---------------------------------------


def test_current_user_is_synthetic_when_auth_is_disabled() -> None:
    request = _FakeRequest(auth_disabled=True, as_user="user-a")
    assert _auth.current_user(request) == AuthedUser("user-a", "user-a@example.test")
    assert _auth.current_user_id(request) == "user-a"


def test_current_user_defaults_to_test_user_when_no_as_user_is_set() -> None:
    request = _FakeRequest(auth_disabled=True)
    assert _auth.current_user_id(request) == "test-user"


def test_current_user_reads_the_session() -> None:
    request = _FakeRequest(
        session={"user": {"id": "abc-123", "email": "operator@example.com"}},
        auth_disabled=False,
    )
    assert _auth.current_user(request) == AuthedUser("abc-123", "operator@example.com")
    assert _auth.current_user_id(request) == "abc-123"


def test_current_user_is_none_without_a_session() -> None:
    request = _FakeRequest(auth_disabled=False)
    assert _auth.current_user(request) is None
    assert _auth.current_user_id(request) is None


def test_current_user_ignores_a_session_without_an_id() -> None:
    """An old cookie (`{"authed": true}`), or a malformed one."""
    for session in ({"authed": True}, {"user": {"email": "x@example.com"}}, {"user": "nope"}):
        request = _FakeRequest(session=session, auth_disabled=False)
        assert _auth.current_user(request) is None
