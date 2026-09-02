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

APP_PY = DASHBOARD / "app.py"
PAGES_DIR = DASHBOARD / "pages"
# The only routes app.py is allowed to declare. Every capability rides the
# two generic `/p/{slug}` routes — a new page is a `Page` spec, not a route.
# The `/documents` and `/jobs` sets are app-native (the dashboard's own stores,
# CLAUDE.md rule 6), not per-capability — the same category as a future
# `/usage` page.
ALLOWED_ROUTES = {
    "/health", "/login", "/logout", "/", "/p/{slug}",
    "/documents", "/documents/new", "/documents/{doc_id}", "/documents/{doc_id}/delete",
    "/jobs", "/jobs/new", "/jobs/{job_id}", "/jobs/{job_id}/analyse", "/jobs/{job_id}/delete",
    # Working drafts — the app's own store (docs/DRAFTS.md), app-native like
    # /documents and /jobs, not a per-capability page.
    "/drafts", "/drafts/{draft_id}", "/drafts/{draft_id}/revise",
    "/drafts/{draft_id}/accept", "/drafts/{draft_id}/undo", "/drafts/{draft_id}/edit",
    "/drafts/{draft_id}/download",
}
ROUTE_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options", "route", "api_route"}


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


def _page_modules():
    """The per-capability page files — everything in `dashboard/pages/`
    except the shared spec and the registry."""
    return [p for p in sorted(PAGES_DIR.glob("*.py")) if p.name not in {"__init__.py", "_spec.py"}]


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


def test_no_page_imports_another_page() -> None:
    """A page mirrors one capability and stands alone. Chaining capabilities
    happens in a page handler calling each `run()` in turn, or in a Prefect
    flow it triggers — never by one page importing another. Only the shared
    `_spec` is a legal cross-page import."""
    offenders: list[str] = []
    for path in _page_modules():
        rel = path.relative_to(DASHBOARD.parent)
        for module, names, lineno in _imports(path):
            parts = module.split(".")
            if parts[:2] != ["dashboard", "pages"]:
                continue
            if len(parts) >= 3 and parts[2] != "_spec":  # import dashboard.pages.other
                offenders.append(f"{rel}:{lineno}: imports {module}")
            elif len(parts) == 2:  # from dashboard.pages import other
                siblings = [n for n in names if n != "_spec"]
                if siblings:
                    offenders.append(f"{rel}:{lineno}: imports {siblings} from dashboard.pages")
    assert not offenders, "a page importing another page:\n  " + "\n  ".join(offenders)


def test_app_adds_no_per_capability_route_or_branch() -> None:
    """Every capability is driven by the two generic `/p/{slug}` routes.
    `app.py` declares no route outside `ALLOWED_ROUTES`, and no handler
    branches on a `slug` value — per-capability behaviour belongs on the
    `Page` spec, not in the router."""
    tree = ast.parse(APP_PY.read_text(), filename=str(APP_PY))
    offenders: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                func = deco.func if isinstance(deco, ast.Call) else None
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "app"
                    and func.attr in ROUTE_DECORATORS
                    and deco.args
                    and isinstance(deco.args[0], ast.Constant)
                    and isinstance(deco.args[0].value, str)
                    and deco.args[0].value not in ALLOWED_ROUTES
                ):
                    offenders.append(
                        f"app.py:{deco.lineno}: new route {deco.args[0].value!r} "
                        f"— a page is a Page spec, not a route"
                    )
        if isinstance(node, ast.Compare):
            for operand in (node.left, *node.comparators):
                if (isinstance(operand, ast.Name) and operand.id == "slug") or (
                    isinstance(operand, ast.Attribute) and operand.attr == "slug"
                ):
                    offenders.append(
                        f"app.py:{node.lineno}: branches on a slug value "
                        f"— per-capability behaviour belongs on the Page spec"
                    )
                    break

    assert not offenders, "app.py has drifted from generic routing:\n  " + "\n  ".join(offenders)


def test_every_page_is_registered_and_well_formed() -> None:
    from dashboard.pages import PAGES, PAGES_BY_SLUG

    assert PAGES, "no pages registered in dashboard/pages/__init__.py"
    assert len(PAGES_BY_SLUG) == len(PAGES), "two pages share a slug"
    for page in PAGES:
        assert page.slug and all(c.isalnum() or c in "-_" for c in page.slug)
        assert page.fields, f"{page.slug}: a page needs at least one field"
        assert callable(page.build_input) and callable(page.sections) and callable(page.run)
        assert page.example_output is not None, f"{page.slug}: example_output is required"
        if page.run_meta is not None:
            meta = page.run_meta(page.example_output)
            assert isinstance(meta.capability, str) and meta.capability
            assert isinstance(meta.capability_version, str) and meta.capability_version
            assert isinstance(meta.cost_usd, float)
            for field in ("input_tokens", "output_tokens",
                          "cache_read_input_tokens", "cache_write_input_tokens"):
                assert isinstance(getattr(meta, field), int), f"{page.slug}: {field} not an int"
