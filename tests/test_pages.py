"""Generic coverage for every registered page.

Add a page to `dashboard/pages/__init__.py` and these tests cover it
automatically — no per-page test to write. The capability's `run()` is
stubbed with `page.example_output`, so nothing here needs an API key or a
network.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from dashboard.app import create_app
from dashboard.pages import PAGES

PAGE_IDS = [p.slug for p in PAGES]


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


def test_index_lists_every_page(client: TestClient) -> None:
    body = client.get("/").text
    for page in PAGES:
        assert page.title in body
        assert f"/p/{page.slug}" in body


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_form_renders_every_declared_field(client: TestClient, page) -> None:
    body = client.get(f"/p/{page.slug}").text
    for field in page.fields:
        assert f'name="{field.name}"' in body, f"{page.slug}: field {field.name!r} not rendered"


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_example_form_fills_required_fields(page) -> None:
    for field in page.fields:
        if field.required:
            assert (page.example_form.get(field.name) or "").strip(), (
                f"{page.slug}: example_form missing required field {field.name!r}"
            )


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_example_submission_runs_end_to_end(page, monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_run(data, **_):  # a slow+progress page is called with on_progress=
        seen["data"] = data
        return page.example_output

    monkeypatch.setattr(page, "run", fake_run)
    client = TestClient(create_app(auth_disabled=True))
    resp = client.post(f"/p/{page.slug}", data=dict(page.example_form))

    assert resp.status_code == 200, resp.text
    assert "data" in seen, f"{page.slug}: page.run was never called"
    assert type(seen["data"]).__name__ == "Input", (
        f"{page.slug}: build_input returned {type(seen['data'])!r}, not the capability Input"
    )
    for section in page.sections(page.example_output):
        assert section.heading in resp.text


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_progress_page_streams_word_count_updates(page, monkeypatch) -> None:
    if not getattr(page, "progress", False):
        pytest.skip("page does not report progress")

    class _P:
        words = 128

    def fake_run(data, *, on_progress=None):
        assert on_progress is not None, f"{page.slug}: on_progress not passed"
        on_progress(_P())
        return page.example_output

    monkeypatch.setattr(page, "run", fake_run)
    client = TestClient(create_app(auth_disabled=True))
    resp = client.post(f"/p/{page.slug}", data=dict(page.example_form))

    assert resp.status_code == 200, resp.text
    assert "window.__progress(128)" in resp.text
    for section in page.sections(page.example_output):
        assert section.heading in resp.text


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_stub_mode_renders_example_output_without_calling_run(page, monkeypatch) -> None:
    def boom(data, **_):
        raise AssertionError(f"{page.slug}: stub mode still called the capability")

    monkeypatch.setattr(page, "run", boom)
    client = TestClient(create_app(auth_disabled=True, stub_runs=True))
    resp = client.post(f"/p/{page.slug}", data=dict(page.example_form))

    assert resp.status_code == 200, resp.text
    assert "Stub mode" in resp.text
    for section in page.sections(page.example_output):
        assert section.heading in resp.text


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_result_shows_run_cost_when_the_page_reports_it(page, monkeypatch) -> None:
    if page.run_meta is None:
        pytest.skip("page's capability reports no cost")

    monkeypatch.setattr(page, "run", lambda data, **_: page.example_output)
    client = TestClient(create_app(auth_disabled=True))
    resp = client.post(f"/p/{page.slug}", data=dict(page.example_form))

    assert resp.status_code == 200, resp.text
    meta = page.run_meta(page.example_output)
    assert f"${meta.cost_usd:.4f}" in resp.text
    assert f"{meta.input_tokens:,} in" in resp.text
    assert f"{meta.output_tokens:,} out" in resp.text
    assert meta.capability in resp.text and meta.capability_version in resp.text


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_result_offers_a_markdown_download_per_section(page, monkeypatch) -> None:
    monkeypatch.setattr(page, "run", lambda data, **_: page.example_output)
    client = TestClient(create_app(auth_disabled=True))
    resp = client.post(f"/p/{page.slug}", data=dict(page.example_form))

    assert resp.status_code == 200, resp.text
    assert "data:text/markdown" in resp.text
    assert resp.text.count('download="') >= len(page.sections(page.example_output))


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_empty_submission_is_rejected_when_fields_are_required(client: TestClient, page) -> None:
    if not any(f.required for f in page.fields):
        pytest.skip("no required fields")
    resp = client.post(f"/p/{page.slug}", data={})
    assert resp.status_code == 422
    assert "run" not in resp.text.lower() or "need attention" in resp.text.lower()


def test_unknown_slug_is_404(client: TestClient) -> None:
    assert client.get("/p/does-not-exist").status_code == 404
