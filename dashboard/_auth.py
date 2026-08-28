"""Single-password session auth. No accounts, no database.

The password is checked against a scrypt hash held in the environment
(`DASHBOARD_PASSWORD_HASH`); a valid login sets a signed session cookie.
If the dashboard ever needs real user accounts, swap the internals here —
no page code changes.

Generate a hash:  `uv run python -m dashboard.hashpw`
"""

from __future__ import annotations

import hashlib
import hmac
import os
from base64 import b64decode, b64encode

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
