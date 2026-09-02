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

# --- area manifest -------------------------------------------------------
# The dashboard hosts self-contained *product areas* that share only the
# shell (CLAUDE.md "## Areas", docs/AREAS.md). This map is the single
# source of truth for the boundary; it lives here so it never ships in the
# runtime. Each area owns a set of `dashboard.*` modules (exact names or
# package prefixes) and the routes it declares in app.py.

SHELL_MODULES = {
    "dashboard",  # dashboard/__init__.py + dashboard/__main__.py
    "dashboard.app", "dashboard._auth", "dashboard._render",
    "dashboard.hashpw", "dashboard.pages", "dashboard.pages._spec",
}
# The composition roots wire the areas into the shell — the page registry
# lists each area's pages, app.py mounts each area's routes. They may
# import area modules; nothing imports them back, and no area imports
# another.
COMPOSITION_ROOTS = {"dashboard.app", "dashboard.pages"}

# The shell's own routes. Every capability still rides the two generic
# `/p/{slug}` routes — a new page is a `Page` spec, not a route.
SHELL_ROUTES = {"/health", "/login", "/logout", "/", "/p/{slug}"}

AREAS = {
    # Job Application Co-Pilot — the incumbent. Stays flat under
    # `dashboard/` for now; the guardrail below isolates it. See
    # docs/AREAS.md for the eventual move under `dashboard/areas/`.
    "job_application": {
        "modules": {
            "dashboard._documents", "dashboard._jobs", "dashboard._drafts",
            "dashboard._job_analysis", "dashboard._targeted_edit",
            "dashboard.pages.cover_letter_writer", "dashboard.pages.cv_writer",
        },
        "routes": {
            "/documents", "/documents/new",
            "/documents/{doc_id}", "/documents/{doc_id}/delete",
            "/jobs", "/jobs/new", "/jobs/{job_id}",
            "/jobs/{job_id}/analyse", "/jobs/{job_id}/delete",
            "/drafts", "/drafts/{draft_id}", "/drafts/{draft_id}/revise",
            "/drafts/{draft_id}/accept", "/drafts/{draft_id}/undo",
            "/drafts/{draft_id}/edit", "/drafts/{draft_id}/download",
        },
    },
    # "event_research": {"modules": {"dashboard.areas.event_research"},
    #                    "routes": {...}},  # added when it lands
}

# The only routes app.py may declare: the shell's plus every area's.
ALLOWED_ROUTES = SHELL_ROUTES | {r for a in AREAS.values() for r in a["routes"]}

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


def _module_name(path: pathlib.Path) -> str:
    """Dotted import name for a file under the repo root:
    `dashboard/pages/cv_writer.py` -> `dashboard.pages.cv_writer`,
    `dashboard/pages/__init__.py` -> `dashboard.pages`."""
    parts = list(path.relative_to(DASHBOARD.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _owner(module: str) -> str | None:
    """Which bucket a `dashboard.*` module belongs to — an area name,
    "shell", or None when the manifest doesn't claim it. Longest matching
    prefix wins, so `dashboard.pages.cv_writer` resolves to its area, not
    to the shell's `dashboard.pages`."""
    best, best_len = None, -1
    buckets = {"shell": SHELL_MODULES, **{a: v["modules"] for a, v in AREAS.items()}}
    for name, entries in buckets.items():
        for entry in entries:
            if (module == entry or module.startswith(entry + ".")) and len(entry) > best_len:
                best, best_len = name, len(entry)
    return best


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


def test_every_dashboard_module_is_claimed_by_the_manifest() -> None:
    """Every `.py` under `dashboard/` is shell or belongs to exactly one
    area — so a new area file can't be added without a manifest entry
    saying which area owns it (and the cross-import check below can't be
    dodged by staying unlisted)."""
    unclaimed = [
        str(p.relative_to(DASHBOARD.parent))
        for p in _source_files()
        if _owner(_module_name(p)) is None
    ]
    assert not unclaimed, (
        "not claimed by the area manifest in tests/test_guardrails.py:\n  "
        + "\n  ".join(unclaimed)
    )


def test_areas_do_not_cross_import() -> None:
    """The area-granularity twin of `test_no_page_imports_another_page`.
    An area's files import only their own area, the shell, and capability
    front doors. Shell files import no area — except the composition roots
    (`dashboard.app`, `dashboard.pages`), which mount the areas."""
    offenders: list[str] = []
    for path in _source_files():
        mod = _module_name(path)
        owner = _owner(mod)
        for imported, names, lineno in _imports(path):
            if imported.split(".")[0] != "dashboard":
                continue
            # `from dashboard import _jobs` names a submodule, not an attr —
            # weigh `dashboard._jobs` too, not just `dashboard`.
            candidates = [imported, *(f"{imported}.{n}" for n in names)]
            targets = {t for c in candidates if (t := _owner(c)) not in (None, "shell")}
            for target in targets:
                if target == owner:
                    continue
                if owner == "shell" and mod in COMPOSITION_ROOTS:
                    continue
                rel = path.relative_to(DASHBOARD.parent)
                whose = f"the {owner} area" if owner and owner != "shell" else "the shell"
                offenders.append(
                    f"{rel}:{lineno}: {whose} imports into the {target} area"
                )
    assert not offenders, "an area reaching into another area:\n  " + "\n  ".join(offenders)


def test_every_route_belongs_to_shell_or_one_area() -> None:
    """`ALLOWED_ROUTES` is the shell's routes plus each area's, kept
    disjoint — so an Event Research route can't be added to app.py without
    declaring which area's set it joins."""
    seen: dict[str, str] = {}
    for area, spec in AREAS.items():
        for route in spec["routes"]:
            assert route not in SHELL_ROUTES, f"{route} is both a shell route and {area}'s"
            assert route not in seen, f"{route} is claimed by both {seen[route]} and {area}"
            seen[route] = area

    tree = ast.parse(APP_PY.read_text(), filename=str(APP_PY))
    declared = {
        deco.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for deco in node.decorator_list
        if isinstance(deco, ast.Call)
        and isinstance(deco.func, ast.Attribute)
        and isinstance(deco.func.value, ast.Name)
        and deco.func.value.id == "app"
        and deco.func.attr in ROUTE_DECORATORS
        and deco.args
        and isinstance(deco.args[0], ast.Constant)
        and isinstance(deco.args[0].value, str)
    }
    unclaimed = declared - SHELL_ROUTES - set(seen)
    assert not unclaimed, (
        "routes in app.py claimed by no area:\n  " + "\n  ".join(sorted(unclaimed))
    )


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
