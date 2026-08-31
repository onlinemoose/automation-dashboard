"""The Job posts area: the app's own store, its screens, the analyse step,
and the picker that loads a saved posting + annotated emphasis into a writer
page.

The store falls back to an in-process dict when Supabase isn't configured
(no env vars in the test run), so nothing here needs a network. The analyse
step calls the `job-analyst` capability; `stub_analyst` below monkeypatches
its `run()` so the suite stays offline, the same way `test_pages.py` stubs a
page's `run`.
"""

from __future__ import annotations

import job_analyst
import pytest
from starlette.testclient import TestClient

from dashboard import _job_analysis, _jobs
from dashboard.app import create_app
from dashboard.pages import cover_letter_writer

POSTING = "Product Lead at Acme\nOwn the roadmap. Work with cross-functional stakeholders."


@pytest.fixture(autouse=True)
def fresh_store():
    _jobs.reset()
    yield
    _jobs.reset()


@pytest.fixture(autouse=True)
def stub_analyst(monkeypatch):
    """Stand in for the job-analyst LLM call so tests never hit the network."""

    def fake_run(data: job_analyst.Input) -> job_analyst.Output:
        first = next((ln.strip() for ln in data.posting.splitlines() if ln.strip()), "the role")
        return job_analyst.Output(
            requirements=[
                job_analyst.Requirement(
                    point="Lead with evidence you can do the core job named in the posting",
                    quote=first[:200],
                    importance="critical",
                    rationale="The headline responsibility.",
                ),
                job_analyst.Requirement(
                    point="Show measurable outcomes, not just responsibilities",
                    quote="",
                    importance="high",
                    rationale="Hiring managers discount duties; numbers land.",
                ),
            ],
            summary=f"This employer is hiring for {first[:120]!r}.",
            reading_between_the_lines=["The seniority bar is higher than the title suggests."],
            cost=job_analyst.Cost(
                usd=0.0,
                input_tokens=0,
                output_tokens=0,
                cache_read_input_tokens=0,
                cache_write_input_tokens=0,
            ),
        )

    monkeypatch.setattr(job_analyst, "run", fake_run)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


# --- the store -------------------------------------------------------------


def test_store_crud_roundtrip() -> None:
    a = _jobs.create_job_post("Acme — Product Lead", POSTING)
    b = _jobs.create_job_post("Bract — PM", "Another posting.")

    assert [j.title for j in _jobs.list_job_posts()] == ["Acme — Product Lead", "Bract — PM"]
    assert _jobs.get_job_post(a.id).posting == POSTING
    assert a.emphasis == ""

    # partial update: emphasis only, title/posting untouched
    _jobs.update_job_post(a.id, emphasis="Lead with roadmap ownership\n- strong here")
    again = _jobs.get_job_post(a.id)
    assert again.title == "Acme — Product Lead"
    assert again.posting == POSTING
    assert "strong here" in again.emphasis

    _jobs.delete_job_post(a.id)
    assert _jobs.get_job_post(a.id) is None
    assert [j.title for j in _jobs.list_job_posts()] == ["Bract — PM"]
    assert b  # keep ref


# --- the screens ---------------------------------------------------------


def test_jobs_page_lists_saved(client: TestClient) -> None:
    _jobs.create_job_post("Acme — Product Lead", POSTING)
    body = client.get("/jobs").text
    assert "Acme — Product Lead" in body
    assert "Own the roadmap" in body


def test_new_job_form_renders(client: TestClient) -> None:
    body = client.get("/jobs/new").text
    assert 'name="title"' in body and 'name="posting"' in body


def test_create_requires_title_and_posting(client: TestClient) -> None:
    resp = client.post("/jobs/new", data={"title": "", "posting": ""})
    assert resp.status_code == 422
    assert "Title is required." in resp.text
    assert _jobs.list_job_posts() == []


def test_create_redirects_to_detail(client: TestClient) -> None:
    resp = client.post(
        "/jobs/new",
        data={"title": "Acme — Product Lead", "posting": POSTING},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    job = _jobs.list_job_posts()[0]
    assert resp.headers["location"] == f"/jobs/{job.id}"


def test_detail_offers_analyse(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING)
    body = client.get(f"/jobs/{job.id}").text
    assert f'action="/jobs/{job.id}/analyse"' in body
    assert 'name="emphasis"' in body


def test_analyse_fills_the_emphasis_list(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING)
    resp = client.post(f"/jobs/{job.id}/analyse")
    assert resp.status_code == 200, resp.text

    stored = _jobs.get_job_post(job.id).emphasis
    assert stored.strip(), "analyse should have written an emphasis list"
    assert "\n> " in stored  # quoted spans
    assert "\n- " in stored  # empty note slots for the candidate


def test_save_persists_annotations(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING)
    annotated = "Lead with roadmap ownership\n> Own the roadmap\n- I did exactly this at Bract"
    resp = client.post(
        f"/jobs/{job.id}",
        data={"title": job.title, "posting": job.posting, "emphasis": annotated},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _jobs.get_job_post(job.id).emphasis == annotated


def test_delete_through_the_ui(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING)
    resp = client.post(f"/jobs/{job.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert _jobs.list_job_posts() == []


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/jobs/nope").status_code == 404


def test_jobs_area_requires_auth() -> None:
    guarded = TestClient(create_app(auth_disabled=False))
    resp = guarded.get("/jobs", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


# --- the emphasis format ------------------------------------------------


def test_parse_plain_lines_are_one_point_each() -> None:
    points = _job_analysis.parse_annotated_emphasis("First point\nSecond point\nThird")
    assert [p.point for p in points] == ["First point", "Second point", "Third"]
    assert all(p.quote is None for p in points)


def test_parse_annotated_block_folds_note_and_keeps_quote() -> None:
    text = (
        "[must-have] Own the roadmap end to end\n"
        "> you will own the product roadmap\n"
        "- I led the roadmap at Bract for two years\n"
    )
    (point,) = _job_analysis.parse_annotated_emphasis(text)
    assert point.point.startswith("Own the roadmap end to end")
    assert "Candidate note: I led the roadmap at Bract for two years" in point.point
    assert point.quote == "you will own the product roadmap"


def test_analysis_text_round_trips_without_notes() -> None:
    analysis = _job_analysis.analyse(POSTING)
    text = _job_analysis.requirements_to_emphasis_text(analysis)
    points = _job_analysis.parse_annotated_emphasis(text)
    assert len(points) == len(analysis.requirements)
    assert points[0].quote  # the quoted span survives
    assert "Candidate note:" not in points[0].point  # empty "- " slots add nothing


# --- wiring into a writer page ------------------------------------------


def test_picker_appears_on_the_writer_page(client: TestClient) -> None:
    _jobs.create_job_post("Acme — Product Lead", POSTING)
    body = client.get("/p/cover-letter-writer").text
    assert 'name="job_post_id"' in body
    assert "Acme — Product Lead" in body


def test_picked_job_post_reaches_the_capability_input(monkeypatch) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING)
    _jobs.update_job_post(
        job.id,
        emphasis="Own the roadmap\n> Own the roadmap\n- strong, did this at Bract",
    )

    seen: dict[str, object] = {}

    def fake_run(data):
        seen["data"] = data
        return cover_letter_writer.PAGE.example_output

    monkeypatch.setattr(cover_letter_writer.PAGE, "run", fake_run)
    client = TestClient(create_app(auth_disabled=True))

    resp = client.post(
        "/p/cover-letter-writer",
        data={
            **dict(cover_letter_writer.PAGE.example_form),
            "job_posting": "",  # picker overrides this
            "job_post_id": job.id,
        },
    )
    assert resp.status_code == 200, resp.text
    data = seen["data"]
    assert data.job_posting == POSTING
    assert len(data.emphasis) == 1
    assert data.emphasis[0].quote == "Own the roadmap"
    assert "Candidate note: strong, did this at Bract" in data.emphasis[0].point
