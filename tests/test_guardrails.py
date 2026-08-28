"""The CLAUDE.md rules, as cheap assertions over the source tree.

`uv run lint-imports` also enforces the no-orchestration-framework rule;
this file adds the checks import-linter can't express (reaching past a
capability's front door into its `_internals`).
"""

from __future__ import annotations

import ast
import pathlib

DASHBOARD = pathlib.Path(__file__).resolve().parent.parent / "dashboard"
BANNED_FRAMEWORKS = {"prefect", "dagster", "airflow", "celery"}


def _imports(path: pathlib.Path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, [a.name for a in node.names], node.lineno
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, [], node.lineno


def _source_files():
    return sorted(DASHBOARD.rglob("*.py"))


def test_no_reaching_past_a_capability_front_door() -> None:
    """Pages import a capability's public names only — never `x._core`
    and never a `_private` name."""
    offenders: list[str] = []
    for path in _source_files():
        rel = path.relative_to(DASHBOARD.parent)
        for module, names, lineno in _imports(path):
            parts = module.split(".")
            if parts[0] == "dashboard":  # the app's own internals are its own affair
                continue
            if any(p.startswith("_") for p in parts[1:]):
                offenders.append(f"{rel}:{lineno}: imports {module}")
            elif len(parts) == 1 and any(n.startswith("_") for n in names):
                offenders.append(f"{rel}:{lineno}: imports {names} from {module}")
    assert not offenders, "reaching past a front door:\n  " + "\n  ".join(offenders)


def test_no_orchestration_framework() -> None:
    offenders: list[str] = []
    for path in _source_files():
        rel = path.relative_to(DASHBOARD.parent)
        for module, _names, lineno in _imports(path):
            if module.split(".")[0] in BANNED_FRAMEWORKS:
                offenders.append(f"{rel}:{lineno}: imports {module}")
    assert not offenders, "orchestration framework in the dashboard:\n  " + "\n  ".join(offenders)


def test_every_page_is_registered_and_well_formed() -> None:
    from dashboard.pages import PAGES, PAGES_BY_SLUG

    assert PAGES, "no pages registered in dashboard/pages/__init__.py"
    assert len(PAGES_BY_SLUG) == len(PAGES), "two pages share a slug"
    for page in PAGES:
        assert page.slug and all(c.isalnum() or c in "-_" for c in page.slug)
        assert page.fields, f"{page.slug}: a page needs at least one field"
        assert callable(page.build_input) and callable(page.sections) and callable(page.run)
        assert page.example_output is not None, f"{page.slug}: example_output is required"
