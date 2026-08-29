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
    # `PORT` is the platform-injected convention (Render, Fly, …); when it's
    # set, bind all interfaces so the platform router can reach us.
    # `DASHBOARD_HOST` / `DASHBOARD_PORT` are our own explicit overrides.
    on_platform = bool(os.environ.get("PORT"))
    host = os.environ.get("DASHBOARD_HOST", "0.0.0.0" if on_platform else "127.0.0.1")
    port = int(os.environ.get("DASHBOARD_PORT") or os.environ.get("PORT") or "8000")
    uvicorn.run("dashboard.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
