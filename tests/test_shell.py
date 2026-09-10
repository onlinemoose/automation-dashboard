"""The shell chrome: UIKit wiring, the topbar, and the nav sidebar.

Page bodies are untouched by this change — the regression signal here is
that a pinned body-content class from an unrelated page (e.g. `/jobs`)
still renders, alongside the new chrome markup.
"""

from __future__ import annotations

import re

import pytest
from starlette.testclient import TestClient

from dashboard._auth import hash_password
from dashboard.app import create_app
from dashboard.pages import PAGES


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


def test_uikit_css_loads_before_app_css_and_js_is_wired(client: TestClient) -> None:
    body = client.get("/").text
    css_pos = body.index("uikit.min.css")
    app_css_pos = body.index("app.css")
    assert css_pos < app_css_pos, "uikit.min.css must load before app.css"
    assert "uikit.min.js" in body
    assert "uikit-icons.min.js" in body


def test_shell_chrome_renders_the_sidebar_and_account_controls(client: TestClient) -> None:
    body = client.get("/").text
    assert "uk-nav" in body
    assert 'id="shell-nav"' in body
    assert "uk-offcanvas" in body
    assert 'href="/jobs"' in body
    assert 'href="/documents"' in body
    assert 'href="/logout"' in body
    assert "test-user@example.test" in body  # the auth_disabled synthetic user's email


def test_login_page_shows_no_sidebar_or_burger() -> None:
    client = TestClient(create_app(auth_disabled=False))
    body = client.get("/login").text
    assert "brand" in body
    assert 'id="shell-nav"' not in body
    assert "uk-offcanvas" not in body
    assert "topbar__burger" not in body


def test_an_existing_page_body_is_unchanged(client: TestClient) -> None:
    # Regression signal: /jobs still carries its pinned body classes —
    # this change touches only the shell chrome around it.
    body = client.get("/jobs").text
    assert "pagelist" in body or "crumb" in body


def test_streamed_slow_page_carries_the_chrome_and_closes_cleanly(monkeypatch) -> None:
    page = next(p for p in PAGES if p.slow)

    def fake_run(data, *, on_progress=None):
        if on_progress is not None:
            on_progress(type("P", (), {"words": 42})())
        return page.example_output

    monkeypatch.setattr(page, "run", fake_run)
    client = TestClient(create_app(auth_disabled=True))
    resp = client.post(f"/p/{page.slug}", data=dict(page.example_form))

    assert resp.status_code == 200, resp.text
    body = resp.text
    assert "uk-nav" in body
    assert 'href="/jobs"' in body
    assert body.count("<div") == body.count("</div>")
    assert body.rstrip().endswith("</html>")
