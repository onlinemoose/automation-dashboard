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

# Must match `create_app`'s default `as_user` — the id the app scopes by
# when auth is disabled.
USER = "test-user"


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
    a = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    b = _jobs.create_job_post("Bract — PM", "Another posting.", USER)

    assert [j.title for j in _jobs.list_job_posts(USER)] == ["Acme — Product Lead", "Bract — PM"]
    assert _jobs.get_job_post(a.id, USER).posting == POSTING
    assert a.emphasis == ""

    assert a.summary == ""

    # partial update: emphasis only, title/posting/summary untouched
    _jobs.update_job_post(a.id, USER, emphasis="Lead with roadmap ownership\n- strong here")
    again = _jobs.get_job_post(a.id, USER)
    assert again.title == "Acme — Product Lead"
    assert again.posting == POSTING
    assert "strong here" in again.emphasis

    # partial update: summary only, emphasis/title/posting untouched
    _jobs.update_job_post(a.id, USER, summary="## Analysis\nThe key theme is roadmap ownership.")
    again = _jobs.get_job_post(a.id, USER)
    assert again.summary == "## Analysis\nThe key theme is roadmap ownership."
    assert "strong here" in again.emphasis
    assert again.posting == POSTING

    _jobs.delete_job_post(a.id, USER)
    assert _jobs.get_job_post(a.id, USER) is None
    assert [j.title for j in _jobs.list_job_posts(USER)] == ["Bract — PM"]
    assert b  # keep ref


def test_job_posts_are_scoped_to_the_user() -> None:
    """A row created by one user is invisible to another — not merely
    unlisted, but unreadable, unwritable and undeletable."""
    mine = _jobs.create_job_post("Acme — Product Lead", POSTING, "user-a")

    assert _jobs.list_job_posts("user-b") == []
    assert _jobs.get_job_post(mine.id, "user-b") is None
    assert _jobs.update_job_post(mine.id, "user-b", title="Hijacked") is None
    assert _jobs.update_job_post(mine.id, "user-b", emphasis="theirs") is None
    _jobs.delete_job_post(mine.id, "user-b")

    still = _jobs.get_job_post(mine.id, "user-a")
    assert still is not None
    assert (still.title, still.posting, still.emphasis) == (
        "Acme — Product Lead", POSTING, "",
    )
    assert still.user_id == "user-a"


def test_the_jobs_page_only_lists_the_callers_posts() -> None:
    a = TestClient(create_app(auth_disabled=True, as_user="user-a"))
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))

    a.post("/jobs/new", data={"title": "Alpha role", "posting": POSTING})

    assert "Alpha role" in a.get("/jobs").text
    assert "Alpha role" not in b.get("/jobs").text


def test_another_users_job_post_is_404_over_http() -> None:
    a = TestClient(create_app(auth_disabled=True, as_user="user-a"))
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))
    a.post("/jobs/new", data={"title": "Alpha role", "posting": POSTING})
    job = _jobs.list_job_posts("user-a")[0]

    assert b.get(f"/jobs/{job.id}").status_code == 404
    assert b.post(
        f"/jobs/{job.id}",
        data={"title": "Hijacked", "posting": "theirs", "emphasis": ""},
    ).status_code == 404
    assert b.post(f"/jobs/{job.id}/analyse").status_code == 404
    b.post(f"/jobs/{job.id}/delete", follow_redirects=False)

    still = _jobs.get_job_post(job.id, "user-a")
    assert still is not None and still.title == "Alpha role"


def test_picker_only_lists_the_callers_jobs() -> None:
    _jobs.create_job_post("Alpha role", POSTING, "user-a")
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))
    body = b.get("/p/cover-letter-writer").text
    assert 'name="job_post_id"' in body
    assert "Alpha role" not in body


def test_another_users_job_id_cannot_be_smuggled_into_a_run(monkeypatch) -> None:
    """Picking a foreign id falls through to the form's own job_posting
    rather than loading that user's saved posting."""
    foreign = _jobs.create_job_post("Alpha role", POSTING, "user-a")

    seen: dict[str, object] = {}

    def fake_run(data, **_):
        seen["data"] = data
        return cover_letter_writer.PAGE.example_output

    monkeypatch.setattr(cover_letter_writer.PAGE, "run", fake_run)
    b = TestClient(create_app(auth_disabled=True, as_user="user-b"))

    resp = b.post(
        "/p/cover-letter-writer",
        data={
            **dict(cover_letter_writer.PAGE.example_form),
            "job_posting": "b's own posting text",
            "job_post_id": foreign.id,
        },
    )
    assert resp.status_code == 200, resp.text
    assert seen["data"].job_posting == "b's own posting text"
    assert POSTING not in seen["data"].job_posting


# --- the screens ---------------------------------------------------------


def test_jobs_list_row_shows_a_capped_posting_preview_and_delete(client: TestClient) -> None:
    """Each row is kept spare: the title, the opening words of the posting
    (capped, not the whole thing, not a bare count), and a delete button
    rendered to the right of the row body."""
    opening = "Own the roadmap and set the product direction end to end"
    long_posting = opening + " " + " ".join(f"tail{i}" for i in range(60))
    job = _jobs.create_job_post("Acme — Product Lead", long_posting, USER)
    body = client.get("/jobs").text

    assert "Acme — Product Lead" in body
    assert opening in body  # the preview starts at the opening sentence
    assert "tail59" not in body  # ...and is capped, not the full posting
    assert f"{len(long_posting.split())} words" not in body  # not a bare word count
    # the row is title + preview + delete only — no analysis status text
    _jobs.update_job_post(job.id, USER, emphasis="a\n> b\n- c")
    assert "lines of emphasis" not in client.get("/jobs").text

    delete = f'action="/jobs/{job.id}/delete"'
    assert delete in body
    assert "button--danger" in body
    # the delete form comes after the row body -> it sits on the right
    assert body.index("pagelist__body") < body.index(delete)


def test_new_job_form_renders(client: TestClient) -> None:
    body = client.get("/jobs/new").text
    assert 'name="title"' in body and 'name="posting"' in body


def test_create_requires_title_and_posting(client: TestClient) -> None:
    resp = client.post("/jobs/new", data={"title": "", "posting": ""})
    assert resp.status_code == 422
    assert "Title is required." in resp.text
    assert _jobs.list_job_posts(USER) == []


def test_create_redirects_to_detail(client: TestClient) -> None:
    resp = client.post(
        "/jobs/new",
        data={"title": "Acme — Product Lead", "posting": POSTING},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    job = _jobs.list_job_posts(USER)[0]
    assert resp.headers["location"] == f"/jobs/{job.id}"


def test_unanalysed_post_reads_and_offers_edit_and_analyse(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    body = client.get(f"/jobs/{job.id}").text
    # The posting is shown for reading, not as an editable form.
    assert "Own the roadmap" in body
    assert 'id="posting"' not in body
    assert 'id="emphasis"' not in body
    # ...with an Edit link and an Analyse button.
    assert f'href="/jobs/{job.id}?edit=1"' in body
    assert f'action="/jobs/{job.id}/analyse"' in body


def test_edit_mode_shows_the_posting_form(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    body = client.get(f"/jobs/{job.id}?edit=1").text
    assert 'id="title"' in body
    assert 'id="posting"' in body


def test_analysed_post_shows_the_structured_emphasis_editor(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    assert client.post(f"/jobs/{job.id}/analyse").status_code == 200
    body = client.get(f"/jobs/{job.id}").text
    assert 'class="emphasis-item"' in body  # one card per analysed requirement
    assert 'name="item_count"' in body  # the rows round-trip through the save
    assert 'name="note_0"' in body  # ...with an editable note per row
    assert 'id="posting"' not in body  # the posting is settled, not shown
    assert f'formaction="/jobs/{job.id}/analyse"' in body  # re-analyse still offered


def test_analyse_fills_the_emphasis_list(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    resp = client.post(f"/jobs/{job.id}/analyse")
    assert resp.status_code == 200, resp.text

    stored = _jobs.get_job_post(job.id, USER).emphasis
    assert stored.strip(), "analyse should have written an emphasis list"
    assert "\n> " in stored  # quoted spans
    assert "\n- " in stored  # empty note slots for the candidate


def test_analyse_empty_result_keeps_the_emphasis_and_warns(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    _jobs.update_job_post(job.id, USER, emphasis="My hand-written notes\n- keep these")

    def empty_run(data: job_analyst.Input) -> job_analyst.Output:
        return job_analyst.Output(
            requirements=[], summary="", reading_between_the_lines=[],
            cost=job_analyst.Cost(0.0, 0, 0, 0, 0),
        )

    monkeypatch.setattr(job_analyst, "run", empty_run)

    resp = client.post(f"/jobs/{job.id}/analyse")
    assert resp.status_code == 502
    assert "came back empty" in resp.text
    assert _jobs.get_job_post(job.id, USER).emphasis == "My hand-written notes\n- keep these"


def test_save_persists_annotations(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    annotated = "Lead with roadmap ownership\n> Own the roadmap\n- I did exactly this at Bract"
    resp = client.post(
        f"/jobs/{job.id}",
        data={"title": job.title, "posting": job.posting, "emphasis": annotated},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _jobs.get_job_post(job.id, USER).emphasis == annotated


def test_analyse_response_shows_the_summary_and_carries_it_for_saving(
    client: TestClient,
) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    body = client.post(f"/jobs/{job.id}/analyse").text
    assert 'class="markdown"' in body  # the summary is rendered for reading
    assert 'name="summary"' in body  # ...and sits in the save form as a hidden field
    # analyse itself does not persist the summary — Save does
    assert _jobs.get_job_post(job.id, USER).summary == ""


def test_save_persists_the_summary_alongside_the_emphasis(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    client.post(f"/jobs/{job.id}/analyse")  # fills emphasis, shows the summary

    summary_md = "## What this employer is weighing\nRoadmap ownership, top to bottom."
    resp = client.post(
        f"/jobs/{job.id}",
        data={
            "title": job.title,
            "posting": job.posting,
            "emphasis": "Lead with roadmap ownership\n- strong here",
            "summary": summary_md,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    saved = _jobs.get_job_post(job.id, USER)
    assert saved.summary == summary_md
    assert "strong here" in saved.emphasis

    # and it comes back on the next view of the analysed job
    body = client.get(f"/jobs/{job.id}").text
    assert "What this employer is weighing" in body


def test_save_from_the_structured_editor_persists_canonical_emphasis(
    client: TestClient,
) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    client.post(f"/jobs/{job.id}/analyse")  # fills the emphasis list

    # the structured editor posts the analysed rows back as hidden fields
    # plus one editable note per row
    resp = client.post(
        f"/jobs/{job.id}",
        data={
            "title": job.title,
            "posting": job.posting,
            "summary": "",
            "item_count": "1",
            "req_0": "Own the roadmap end to end",
            "tag_0": "must-have",
            "quote_0": "Own the roadmap",
            "note_0": "Led this at Bract for two years",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    stored = _jobs.get_job_post(job.id, USER).emphasis
    assert stored == (
        "[must-have] Own the roadmap end to end\n"
        "> Own the roadmap\n"
        "- Led this at Bract for two years\n"
    )
    # and it still reads back for the writer pages
    (point,) = _job_analysis.parse_annotated_emphasis(stored)
    assert "Candidate note: Led this at Bract for two years" in point.point


def test_delete_through_the_ui(client: TestClient) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    resp = client.post(f"/jobs/{job.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert _jobs.list_job_posts(USER) == []


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


def test_parse_emphasis_items_reads_tag_quote_and_note() -> None:
    text = (
        "[must-have] Own the roadmap end to end\n"
        "> you will own the product roadmap\n"
        "- I led the roadmap at Bract for two years\n"
    )
    (item,) = _job_analysis.parse_emphasis_items(text)
    assert item.importance == "must-have"
    assert item.requirement == "Own the roadmap end to end"
    assert item.quote == "you will own the product roadmap"
    assert item.note == "I led the roadmap at Bract for two years"


def test_emphasis_items_round_trip_matches_the_canonical_text() -> None:
    original = _job_analysis.requirements_to_emphasis_text(_job_analysis.analyse(POSTING))
    items = _job_analysis.parse_emphasis_items(original)
    assert _job_analysis.emphasis_items_to_text(items) == original


def test_emphasis_items_to_text_is_read_back_by_the_writer_parse() -> None:
    items = [
        _job_analysis.EmphasisItem(
            requirement="Own the roadmap",
            quote="own the product roadmap",
            importance="must-have",
            note="did this at Bract",
        )
    ]
    text = _job_analysis.emphasis_items_to_text(items)
    (point,) = _job_analysis.parse_annotated_emphasis(text)
    assert point.quote == "own the product roadmap"
    assert "Candidate note: did this at Bract" in point.point


# --- wiring into a writer page ------------------------------------------


def test_picker_appears_on_the_writer_page(client: TestClient) -> None:
    _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    body = client.get("/p/cover-letter-writer").text
    assert 'name="job_post_id"' in body
    assert "Acme — Product Lead" in body


def test_picked_job_post_reaches_the_capability_input(monkeypatch) -> None:
    job = _jobs.create_job_post("Acme — Product Lead", POSTING, USER)
    _jobs.update_job_post(
        job.id, USER,
        emphasis="Own the roadmap\n> Own the roadmap\n- strong, did this at Bract",
    )

    seen: dict[str, object] = {}

    def fake_run(data, **_):
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
