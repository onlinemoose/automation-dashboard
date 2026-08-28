"""Print a DASHBOARD_PASSWORD_HASH for `.env`.

    uv run python -m dashboard.hashpw
"""

from __future__ import annotations

import getpass

from dashboard._auth import hash_password


def main() -> None:
    first = getpass.getpass("Dashboard password: ")
    if not first:
        raise SystemExit("empty password")
    if first != getpass.getpass("Confirm password: "):
        raise SystemExit("passwords did not match")
    print(hash_password(first))


if __name__ == "__main__":
    main()
