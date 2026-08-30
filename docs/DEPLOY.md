# Deploying the dashboard

This app is its own deployable — one `uvicorn` process behind a reverse
proxy. Capabilities are installed dependencies inside it; they are never
deployed separately.

> **Target host: Render.** `docs/DEPLOYMENT_CHECKLIST.md` has the
> Render-specific plan, a `render.yaml` template, and the running task
> list (auth, database, calendar). This file stays host-agnostic.

## Environment

Set these in the process environment (not committed):

| Variable | Purpose |
|---|---|
| `SESSION_SECRET` | signs the login cookie; a long random string. `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DASHBOARD_PASSWORD_HASH` | the login password, hashed. `uv run python -m dashboard.hashpw` |
| `ANTHROPIC_API_KEY` | passed through to any capability that calls Claude |
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | backing store for the Background documents area (`docs/BACKGROUND_DOCUMENTS.md`). Unset → an in-memory fallback that does not survive a restart |
| `DASHBOARD_HTTPS` | `1` in production — marks the session cookie `Secure` |
| `DASHBOARD_HOST` / `DASHBOARD_PORT` | optional; default `127.0.0.1:8000` |

## Run

```
uv sync --frozen           # install exactly what uv.lock pins
uv run dashboard           # or: uv run uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
```

`uv.lock` pins every capability to an exact commit, so a deploy is
reproducible and a bad capability upgrade is a one-line revert.

## Reverse proxy

Terminate TLS at nginx / Caddy / a platform router and proxy to the
uvicorn port. Point a subdomain at it (e.g. `tools.example.net`). Set
`DASHBOARD_HTTPS=1` so the cookie is `Secure`.

Caddy example:

```
tools.example.net {
    reverse_proxy 127.0.0.1:8000
}
```

## As a service (systemd sketch)

```ini
[Service]
WorkingDirectory=/srv/automation-dashboard
EnvironmentFile=/srv/automation-dashboard/.env
ExecStart=/usr/bin/uv run uvicorn dashboard.app:app --host 127.0.0.1 --port 8000
Restart=on-failure
```

## Notes

- Single-password auth suits one operator. For more than one person, or
  audit needs, replace the internals of `dashboard/_auth.py` with real
  accounts — no page code changes.
- The Background documents store is the app's own (`dashboard/_documents.py`,
  a Supabase table). It is the first piece of app-owned persistence; a
  future usage store would sit beside it. See `docs/BACKGROUND_DOCUMENTS.md`.
- Long LLM calls block the worker. With one operator that is fine; under
  real concurrency, run several uvicorn workers or add a job queue.
