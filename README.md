# experience-layer-template

A starting point for **the experience layer** of the automation system: a
small web app that puts a usable face on the capability modules. One page
per capability — the form fields are that capability's inputs, the
results view is its output. The app collects the form, calls the
capability's `run()`, and renders what comes back. No domain logic of its
own.

The rules are in **`CLAUDE.md`** (Claude Code reads it automatically).
The prose version and the "add a page" walk-through are in
**`docs/EXPERIENCE.md`**.

Sibling of `capability-module-template`. Where that repo is the pattern
for *one job*, this is the pattern for *the app people use to run those
jobs*.

---

## One-time setup

- **`uv`** — `uv --version`, or install:
  `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Make a new dashboard from this template

### 1. New repo

On GitHub, **Use this template**, name it (e.g. `automation-dashboard`),
clone it. Set `name` in `pyproject.toml` to match.

### 2. Clear the worked example

Delete `dashboard/_example_capability.py`, `dashboard/pages/example.py`,
and its line in `dashboard/pages/__init__.py`. (Leave them while you find
your feet — the app runs as-is.)

### 3. Configure

```
cp .env.example .env
uv run python -m dashboard.hashpw     # paste the hash into DASHBOARD_PASSWORD_HASH
python -c "import secrets; print(secrets.token_urlsafe(32))"   # -> SESSION_SECRET
```

### 4. Add your first capability page

Follow `docs/EXPERIENCE.md` → **Adding a page**. In short: `uv add` the
capability at a pinned git tag, copy `dashboard/pages/example.py`, wire
it to the real `run` / `Input` / `Output`, register it.

### 5. Run it

```
uv run dashboard          # http://127.0.0.1:8000
uv run pytest             # every page renders + runs end to end
uv run lint-imports       # no orchestration framework crept in
```

---

## How it fits the system

- Depends on capabilities as **pinned git dependencies**
  (`<name> @ git+https://…@vX.Y.Z`), recorded in `uv.lock`. Calls their
  `run()` directly. Nothing depends on this app.
- May **trigger** a Prefect pipeline via its API, but never defines
  flows or tasks.
- Deploys as **one service** — see `docs/DEPLOY.md`. Capabilities ride
  along as installed dependencies.

Full architecture: `automation-architecture/ARCHITECTURE.md`.
