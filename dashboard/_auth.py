"""Session auth, backed by Supabase Auth.

Sign-in is email + password against Supabase Auth (the *anon* key, not
the service key); a valid login puts `{"id", "email"}` into the signed
session cookie, which stays the session of record. Every row the app
stores is scoped to that id — see `docs/USER_SCOPING.md`.

When `SUPABASE_ANON_KEY` is blank the module falls back to an offline
backend that checks the submitted email against `DASHBOARD_DEV_EMAIL` and
the password against the scrypt hash in `DASHBOARD_PASSWORD_HASH` — the
same shape as the in-memory store fallbacks, so local dev and the test
suite run without Supabase. That is the *only* remaining use of the
scrypt helpers below; production auth is Supabase.

Generate a dev hash:  `uv run python -m dashboard.hashpw`
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import warnings
from base64 import b64decode, b64encode
from dataclasses import dataclass
from typing import Protocol

from starlette.requests import Request

# scrypt cost parameters — fixed, and encoded into the hash string.
_N, _R, _P = 2**14, 8, 1


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt if salt is not None else os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${b64encode(salt).decode()}${b64encode(dk).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt_b64, dk_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        salt = b64decode(salt_b64)
        expected = b64decode(dk_b64)
    except Exception:
        return False
    dk = hashlib.scrypt(
        password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=len(expected)
    )
    return hmac.compare_digest(dk, expected)


def password_hash() -> str:
    """The configured hash, read fresh each call so tests can set it."""
    return os.environ.get("DASHBOARD_PASSWORD_HASH", "")


def is_authed(request: Request) -> bool:
    if getattr(request.app.state, "auth_disabled", False):
        return True
    return bool(request.session.get("authed"))


# --- who is signed in -----------------------------------------------------


@dataclass(frozen=True)
class AuthedUser:
    """The signed-in operator: a Supabase `auth.users` id and their email.

    The id is what every app-owned row is scoped by, so it is the one
    field the stores care about.
    """

    id: str
    email: str


class _AuthBackend(Protocol):
    def sign_in(self, email: str, password: str) -> AuthedUser | None: ...


class _MemoryAuthBackend:
    """Offline / test fallback. Only used when Supabase Auth isn't configured.

    Reads its config fresh on every `sign_in` rather than caching it in
    `__init__` — the backend itself is a process-wide singleton, so a test
    that sets `DASHBOARD_PASSWORD_HASH` or `DASHBOARD_DEV_EMAIL` after
    first use must still be honoured.
    """

    ID = "test-user"

    def sign_in(self, email: str, password: str) -> AuthedUser | None:
        expected_hash = password_hash()
        if not expected_hash:
            return None
        expected_email = os.environ.get("DASHBOARD_DEV_EMAIL") or "operator@example.com"
        if (email or "").strip().lower() != expected_email.strip().lower():
            return None
        if not verify_password(password, expected_hash):
            return None
        return AuthedUser(id=self.ID, email=expected_email)


class _SupabaseAuthBackend:
    def __init__(self, url: str, anon_key: str) -> None:
        from supabase import create_client

        self._client = create_client(url, anon_key)

    def sign_in(self, email: str, password: str) -> AuthedUser | None:
        try:
            res = self._client.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception:  # noqa: BLE001 - gotrue's error types vary by version
            return None
        user = getattr(res, "user", None)
        if user is None or not getattr(user, "id", None):
            return None
        return AuthedUser(id=str(user.id), email=str(getattr(user, "email", "") or email))


_auth_backend_instance: _AuthBackend | None = None
_backend_lock = threading.Lock()


def _auth_backend() -> _AuthBackend:
    """The auth backend, chosen once from the environment."""
    global _auth_backend_instance
    if _auth_backend_instance is not None:
        return _auth_backend_instance
    with _backend_lock:
        if _auth_backend_instance is None:
            url = os.environ.get("SUPABASE_URL")
            anon_key = os.environ.get("SUPABASE_ANON_KEY")
            if url and anon_key:
                _auth_backend_instance = _SupabaseAuthBackend(url, anon_key)
            else:
                warnings.warn(
                    "SUPABASE_URL / SUPABASE_ANON_KEY are not set — falling back "
                    "to the offline login (DASHBOARD_DEV_EMAIL + "
                    "DASHBOARD_PASSWORD_HASH). Set both for real accounts.",
                    stacklevel=2,
                )
                _auth_backend_instance = _MemoryAuthBackend()
    return _auth_backend_instance


def reset() -> None:
    """Drop the chosen backend so it is re-selected. For tests only."""
    global _auth_backend_instance
    with _backend_lock:
        _auth_backend_instance = None


def sign_in(email: str, password: str) -> AuthedUser | None:
    """The signed-in user for these credentials, or None if they're wrong."""
    return _auth_backend().sign_in(email, password)


def current_user(request: Request) -> AuthedUser | None:
    """Who this request is from, read from the signed session cookie."""
    state = request.app.state
    if getattr(state, "auth_disabled", False):
        uid = getattr(state, "as_user", "test-user")
        return AuthedUser(id=uid, email=f"{uid}@example.test")
    stored = request.session.get("user")
    if isinstance(stored, dict) and stored.get("id"):
        return AuthedUser(id=str(stored["id"]), email=str(stored.get("email") or ""))
    return None


def current_user_id(request: Request) -> str | None:
    user = current_user(request)
    return user.id if user is not None else None
