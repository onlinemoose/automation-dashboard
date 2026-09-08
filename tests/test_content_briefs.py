"""The Content Creation Team area: the Content briefs store, the screens,
running the team from a brief, and sending a piece back for revision.

The store falls back to an in-process dict when Supabase isn't configured
(no env vars in the test run). `stub_team` monkeypatches
`content_creation_team.run` so the suite stays offline, the same way
`test_jobs.py` stubs `job_analyst.run`.
"""

from __future__ import annotations

import content_creation_team
import pytest
from starlette.testclient import TestClient

from dashboard.app import create_app
from dashboard.areas.content_creation_team import _briefs, _content_drafts

# Must match `create_app`'s default `as_user`.
USER = "test-user"
OTHER = "other-user"

_seen: dict[str, object] = {}


def _output(goal: str = "a goal", *, approved: bool = True, stopped_on: str = "approved"):
    return content_creation_team.Output(
        final_copy=f"# {goal[:30]}\n\nThe body of the piece.",
        title="A title",
        excerpt="An excerpt.",
        slug="a-title",
        tags=["x", "y"],
        approved=approved,
        stopped_on=stopped_on,
        research_notes="RN",
        seo_brief="SB",
        editor_notes="EN",
        seo_notes="SN",
        revision_history=[
            content_creation_team.RevisionRound(
                round=1, draft="d", editor_verdict="approved", editor_notes="ok",
                seo_verdict="approved", seo_notes="ok",
            )
        ],
        cost=content_creation_team.Cost(0.1, 10, 5, 0, 2),
    )


@pytest.fixture(autouse=True)
def fresh_store():
    _briefs.reset()
    _content_drafts.reset()
    _seen.clear()
    yield
    _briefs.reset()
    _content_drafts.reset()


@pytest.fixture(autouse=True)
def stub_team(monkeypatch):
    def fake_run(data: content_creation_team.Input) -> content_creation_team.Output:
        _seen["input"] = data
        return _output(data.goal, approved=_seen.get("approved", True),
                       stopped_on=_seen.get("stopped_on", "approved"))

    monkeypatch.setattr(content_creation_team, "run", fake_run)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


def _make_brief(user_id: str = USER, **over) -> _briefs.ContentBrief:
    brief = _briefs.create_brief(
        over.get("title", "T"), over.get("goal", "G" * 20),
        over.get("content_brief", "B" * 20), user_id,
    )
    knobs = {k: v for k, v in over.items() if k not in ("title", "goal", "content_brief")}
    if knobs:
        brief = _briefs.update_brief(brief.id, user_id, **knobs)
    return brief


# --- the store --------------------------------------------------------


def test_create_and_get_roundtrip():
    brief = _briefs.create_brief("T", "goal", "brief text", USER)
    got = _briefs.get_brief(brief.id, USER)
    assert got is not None
    assert (got.title, got.goal, got.content_brief) == ("T", "goal", "brief text")
    assert got.piece is None and got.runs == []
    assert got.max_usd == 2.0 and got.target_length_words == 0


def test_update_is_a_partial_merge():
    brief = _make_brief(audience="managers")
    _briefs.update_brief(brief.id, USER, goal="new goal")
    got = _briefs.get_brief(brief.id, USER)
    assert got.goal == "new goal"
    assert got.audience == "managers"  # untouched
    # piece / runs are independent of a knob update
    _briefs.update_brief(brief.id, USER, piece={"final_copy": "x"}, runs=[{"a": 1}])
    _briefs.update_brief(brief.id, USER, title="renamed")
    got = _briefs.get_brief(brief.id, USER)
    assert got.title == "renamed"
    assert got.piece == {"final_copy": "x"} and got.runs == [{"a": 1}]


def test_user_scoping_hides_a_foreign_brief():
    brief = _make_brief(OTHER)
    assert _briefs.get_brief(brief.id, USER) is None
    assert _briefs.update_brief(brief.id, USER, goal="hijack") is None
    _briefs.delete_brief(brief.id, USER)  # no-op
    assert _briefs.get_brief(brief.id, OTHER) is not None
    assert [b.id for b in _briefs.list_briefs(USER)] == []


# --- the screens -----------------------------------------------------


def test_area_requires_auth():
    client = TestClient(create_app(auth_disabled=False))
    r = client.get("/content", follow_redirects=False)
    assert r.status_code == 303 and "/login" in r.headers["location"]


def test_list_shows_only_the_callers_briefs(client: TestClient):
    _make_brief(USER, title="Mine")
    _make_brief(OTHER, title="Theirs")
    body = client.get("/content").text
    assert "Mine" in body and "Theirs" not in body


def test_new_brief_needs_the_required_fields(client: TestClient):
    r = client.post("/content/new", data={"title": "", "goal": "", "content_brief": ""})
    assert r.status_code == 422
    assert "need attention" in r.text.lower()


def test_create_redirects_to_the_detail(client: TestClient):
    r = client.post(
        "/content/new",
        data={"title": "T", "goal": "g" * 20, "content_brief": "b" * 20},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"].startswith("/content/")


def test_detail_prefills_and_save_round_trips_the_list_fields(client: TestClient):
    brief = _make_brief()
    r = client.post(
        f"/content/{brief.id}",
        data={
            "title": "T", "goal": "g" * 20, "content_brief": "b" * 20,
            "topic_areas": "leadership\nmanaging others",
            "target_keywords": "quiet meetings\npsychological safety",
            "target_length_words": "1100",
            "max_usd": "3.5", "max_editor_revisions": "4", "max_seo_revisions": "2",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    got = _briefs.get_brief(brief.id, USER)
    assert got.topic_areas == "leadership\nmanaging others"
    assert got.target_length_words == 1100 and got.max_usd == 3.5
    assert got.max_editor_revisions == 4 and got.max_seo_revisions == 2
    # and they render back into the form
    body = client.get(f"/content/{brief.id}").text
    assert "leadership\nmanaging others" in body
    # Tone was removed — it overlapped house_style and the capability's own
    # prompts. The form must not carry it.
    assert 'name="tone"' not in body and ">Tone<" not in body


def test_detail_offers_the_bundled_default_house_style(client: TestClient):
    from dashboard.areas.content_creation_team.pages.content_creation_team import (
        DEFAULT_HOUSE_STYLE,
    )

    brief = _make_brief()
    body = client.get(f"/content/{brief.id}").text
    # the link and the embedded default the click-handler reads from
    assert 'id="house-style-default-link"' in body
    assert 'id="house-style-default"' in body
    assert "British English unless a supplied" in DEFAULT_HOUSE_STYLE
    assert "British English unless a supplied" in body


def test_delete_removes_the_brief(client: TestClient):
    brief = _make_brief()
    r = client.post(f"/content/{brief.id}/delete", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/content"
    assert _briefs.get_brief(brief.id, USER) is None


def test_foreign_brief_is_404_over_http(client: TestClient):
    brief = _make_brief(OTHER)
    assert client.get(f"/content/{brief.id}").status_code == 404
    assert client.post(f"/content/{brief.id}/run").status_code == 404
    assert client.post(f"/content/{brief.id}/send-back", data={"notes": "x"}).status_code == 404


# --- running the team ----------------------------------------------


def test_run_from_a_brief_persists_the_piece(client: TestClient):
    brief = _make_brief(goal="demonstrate the know-best tendency")
    r = client.post(f"/content/{brief.id}/run")
    assert r.status_code == 200
    for heading in ("Publishing metadata", "Final copy", "Revision history"):
        assert heading in r.text
    got = _briefs.get_brief(brief.id, USER)
    assert got.piece is not None
    assert got.piece["research_notes"] == "RN" and got.piece["seo_brief"] == "SB"
    assert got.piece["final_copy"].startswith("# demonstrate")
    assert got.piece["meta"]["capability"] == "content-creation-team"
    assert len(got.runs) == 1 and got.runs[0]["stopped_on"] == "approved"
    # the Input the capability saw
    assert isinstance(_seen["input"], content_creation_team.Input)
    assert _seen["input"].max_usd == 2.0


def test_flagged_run_shows_the_not_approved_banner(client: TestClient):
    _seen["approved"] = False
    _seen["stopped_on"] = "cost_cap"
    brief = _make_brief()
    r = client.post(f"/content/{brief.id}/run")
    assert "shipped without full approval" in r.text.lower()
    assert "cost_cap" in r.text
    assert _briefs.get_brief(brief.id, USER).piece["approved"] is False


def test_send_back_resumes_from_the_saved_notes(client: TestClient):
    brief = _make_brief()
    client.post(f"/content/{brief.id}/run")
    first_copy = _briefs.get_brief(brief.id, USER).piece["final_copy"]
    _seen.pop("input")

    r = client.post(
        f"/content/{brief.id}/send-back",
        data={"notes": "tighten the open\ncut the third example"},
    )
    assert r.status_code == 200
    sent = _seen["input"]
    assert sent.previous_draft == first_copy
    assert len(sent.previous_feedback) == 2
    assert sent.research_notes == "RN" and sent.seo_brief == "SB"
    got = _briefs.get_brief(brief.id, USER)
    assert len(got.runs) == 2


def test_send_back_needs_a_finished_piece_and_a_note(client: TestClient):
    brief = _make_brief()
    assert client.post(f"/content/{brief.id}/send-back", data={"notes": "x"}).status_code == 400
    client.post(f"/content/{brief.id}/run")
    assert client.post(f"/content/{brief.id}/send-back", data={"notes": "   "}).status_code == 422


def test_stub_mode_runs_without_calling_the_capability(monkeypatch):
    def boom(data):
        raise AssertionError("stub mode still called content_creation_team.run")

    monkeypatch.setattr(content_creation_team, "run", boom)
    client = TestClient(create_app(auth_disabled=True, stub_runs=True))
    brief = _make_brief()
    r = client.post(f"/content/{brief.id}/run")
    assert r.status_code == 200 and "Final copy" in r.text
    assert _briefs.get_brief(brief.id, USER).piece is None  # nothing persisted
