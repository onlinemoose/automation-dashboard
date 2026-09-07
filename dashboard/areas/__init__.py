"""Product areas — self-contained slices that share only the shell.

Each area lives in `dashboard/areas/<name>/` and exposes one `AREA`
object (`dashboard.pages._spec.Area`). The composition roots fold them
in: `dashboard/pages/__init__.py` adds each area's pages to `PAGES`,
`dashboard/app.py` mounts each area's router. Areas never import each
other — `tests/test_guardrails.py` makes that a failing test. See
`docs/AREAS.md`.
"""
