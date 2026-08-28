"""Run the dashboard: `uv run dashboard` or `python -m dashboard`."""

from __future__ import annotations

import os

try:  # load .env in local dev, same as the capability CLIs
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:
    pass

import uvicorn


def main() -> None:
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT", "8000"))
    uvicorn.run("dashboard.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
