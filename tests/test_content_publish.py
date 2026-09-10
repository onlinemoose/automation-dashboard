"""Publish to website: the `_publish.py` adapter, the `/content/{id}/publish`
route, and `_feldklang_repo.py`'s GitHub commit client (against a mocked
`httpx` transport — no live network, no real repo).
"""

from __future__ import annotations

import json

import httpx
import publish_to_website as ptw
import pytest
from starlette.testclient import TestClient

from dashboard.app import create_app
from dashboard.areas.content_creation_team import _briefs, _feldklang_repo as fk, _publish

USER = "test-user"

_POST_CONTENT = "---\ntitle: A title\n---\n\nBody.\n"
_IMAGE_BYTES = b"\xff\xd8\xff" + b"fake-jpeg-bytes"


@pytest.fixture(autouse=True)
def fresh_store():
    _briefs.reset()
    yield
    _briefs.reset()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(auth_disabled=True))


def _make_brief_with_piece(user_id: str = USER, **piece_over) -> _briefs.ContentBrief:
    brief = _briefs.create_brief("T", "G" * 20, "B" * 20, user_id)
    piece = {
        "final_copy": "# A title\n\nBody.",
        "title": "A title",
        "excerpt": "An excerpt.",
        "slug": "a-title",
        "tags": ["x", "y"],
        "approved": True,
        "stopped_on": "approved",
        "sections": [],
        "meta": None,
        "saved_at": "2026-09-10T00:00:00+00:00",
    }
    piece.update(piece_over)
    return _briefs.update_brief(brief.id, user_id, piece=piece)


def _fake_output(**over) -> ptw.Output:
    defaults = dict(
        post_path="src/data/post/a-title.mdx",
        post_content=_POST_CONTENT,
        image_path="src/assets/images/a-title-hero.jpg",
        image_bytes=_IMAGE_BYTES,
        image_prompt_used="a prompt",
        cost=ptw.Cost(usd=0.04, notes="Recraft recraftv3 generation"),
    )
    defaults.update(over)
    return ptw.Output(**defaults)


# --- _publish.build_input ------------------------------------------------


def test_build_input_maps_the_stored_piece():
    piece = {"title": "T", "excerpt": "E", "slug": "s", "tags": ["a", "b"], "final_copy": "Body"}
    data = _publish.build_input(piece)
    assert (data.title, data.excerpt, data.slug, data.tags) == ("T", "E", "s", ["a", "b"])
    assert data.body_markdown == "Body"


def test_build_input_applies_form_overrides():
    piece = {"title": "T", "excerpt": "E", "slug": "s", "tags": ["a"], "final_copy": "Body"}
    data = _publish.build_input(
        piece, overrides={"title": "New title", "slug": "new-slug", "tags": ["x", "y"]}
    )
    assert data.title == "New title"
    assert data.slug == "new-slug"
    assert data.tags == ["x", "y"]
    assert data.excerpt == "E"  # untouched — no override given


def test_build_input_blank_override_falls_back_to_the_piece():
    piece = {"title": "T", "excerpt": "E", "slug": "s", "tags": [], "final_copy": "Body"}
    data = _publish.build_input(piece, overrides={"title": "   "})
    assert data.title == "T"


# --- the route -----------------------------------------------------------


def test_publish_form_redirects_when_no_finished_piece(client: TestClient):
    brief = _briefs.create_brief("T", "G" * 20, "B" * 20, USER)
    r = client.get(f"/content/{brief.id}/publish", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"/content/{brief.id}"


def test_publish_stub_mode_calls_neither_capability_nor_github(monkeypatch):
    def boom_run(data):
        raise AssertionError("stub mode still called publish_to_website.run")

    def boom_commit(**kw):
        raise AssertionError("stub mode still called _feldklang_repo.commit_post")

    monkeypatch.setattr(_publish, "run", boom_run)
    monkeypatch.setattr(fk, "commit_post", boom_commit)
    client = TestClient(create_app(auth_disabled=True, stub_runs=True))
    brief = _make_brief_with_piece()
    r = client.post(f"/content/{brief.id}/publish")
    assert r.status_code == 200
    assert "feldklang.netlify.app" in r.text
    # stub mode never persists a real publish onto the brief
    assert _briefs.get_brief(brief.id, USER).piece.get("published") is None


def test_publish_success_writes_piece_published_and_shows_the_url(monkeypatch, client: TestClient):
    monkeypatch.setattr(_publish, "run", lambda data: _fake_output())
    monkeypatch.setattr(
        fk, "commit_post",
        lambda **kw: fk.CommitResult(commit_sha="abc123", post_url="https://feldklang.netlify.app/a-title"),
    )
    brief = _make_brief_with_piece()
    r = client.post(f"/content/{brief.id}/publish")
    assert r.status_code == 200
    assert "https://feldklang.netlify.app/a-title" in r.text
    assert "abc123" in r.text
    got = _briefs.get_brief(brief.id, USER)
    published = got.piece["published"]
    assert published["commit_sha"] == "abc123"
    assert published["post_url"] == "https://feldklang.netlify.app/a-title"


def test_capability_failure_leaves_the_brief_untouched(monkeypatch, client: TestClient):
    def boom(data):
        raise RuntimeError("RECRAFT_API_TOKEN is not set")

    monkeypatch.setattr(_publish, "run", boom)
    brief = _make_brief_with_piece()
    r = client.post(f"/content/{brief.id}/publish")
    assert r.status_code == 422
    assert "RECRAFT_API_TOKEN" in r.text
    assert _briefs.get_brief(brief.id, USER).piece.get("published") is None


def test_commit_failure_leaves_the_brief_untouched_and_shows_the_error(monkeypatch, client: TestClient):
    monkeypatch.setattr(_publish, "run", lambda data: _fake_output())

    def boom(**kw):
        raise fk.PublishError("a-title already exists in feldklang — publish under a new slug.")

    monkeypatch.setattr(fk, "commit_post", boom)
    brief = _make_brief_with_piece()
    r = client.post(f"/content/{brief.id}/publish")
    assert r.status_code == 422
    assert "already exists" in r.text
    assert _briefs.get_brief(brief.id, USER).piece.get("published") is None


def test_second_publish_without_confirm_is_refused(monkeypatch, client: TestClient):
    monkeypatch.setattr(_publish, "run", lambda data: _fake_output())
    monkeypatch.setattr(
        fk, "commit_post",
        lambda **kw: fk.CommitResult(commit_sha="abc123", post_url="https://feldklang.netlify.app/a-title"),
    )
    brief = _make_brief_with_piece()
    first = client.post(f"/content/{brief.id}/publish")
    assert first.status_code == 200

    def boom(**kw):
        raise AssertionError("should not commit again without confirm_republish")

    monkeypatch.setattr(fk, "commit_post", boom)
    second = client.post(f"/content/{brief.id}/publish")
    assert second.status_code == 409
    assert "already been published" in second.text


def test_republish_with_confirm_is_allowed(monkeypatch, client: TestClient):
    monkeypatch.setattr(_publish, "run", lambda data: _fake_output())
    monkeypatch.setattr(
        fk, "commit_post",
        lambda **kw: fk.CommitResult(commit_sha="abc123", post_url="https://feldklang.netlify.app/a-title"),
    )
    brief = _make_brief_with_piece()
    client.post(f"/content/{brief.id}/publish")
    monkeypatch.setattr(
        fk, "commit_post",
        lambda **kw: fk.CommitResult(commit_sha="def456", post_url="https://feldklang.netlify.app/a-title-2"),
    )
    r = client.post(f"/content/{brief.id}/publish", data={"confirm_republish": "1"})
    assert r.status_code == 200
    assert _briefs.get_brief(brief.id, USER).piece["published"]["commit_sha"] == "def456"


def test_foreign_brief_publish_route_is_404(client: TestClient):
    brief = _make_brief_with_piece(user_id="other-user")
    assert client.get(f"/content/{brief.id}/publish").status_code == 404
    assert client.post(f"/content/{brief.id}/publish").status_code == 404


# --- _feldklang_repo.commit_post, against a mocked httpx transport ------


def _handler_sequence(
    calls: list,
    *,
    ff_fails: int = 0,
    collision_paths: frozenset = frozenset(),
    compare_files: list | None = None,
    compare_ahead_by: int = 1,
    compare_behind_by: int = 0,
):
    """A stateful handler implementing the Git Data API sequence
    `commit_post` walks. `ff_fails` PATCHes return 422 (non-fast-forward)
    before one succeeds. `collision_paths` are `/contents/<path>` checks
    that return 200 (already exists) instead of 404."""
    state = {"patch_attempts": 0}
    if compare_files is None:
        compare_files = [
            {"filename": "src/data/post/a-title.mdx", "status": "added"},
            {"filename": "src/assets/images/a-title-hero.jpg", "status": "added"},
        ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url), request.content))
        path = request.url.path

        if request.method == "GET" and path == "/repos/onlinemoose/feldklang":
            return httpx.Response(200, json={"default_branch": "master"})
        if request.method == "GET" and path.endswith("/git/ref/heads/master"):
            return httpx.Response(200, json={"object": {"sha": "base-sha"}})
        if request.method == "GET" and "/git/commits/" in path:
            return httpx.Response(200, json={"tree": {"sha": "base-tree-sha"}})
        if request.method == "GET" and "/contents/" in path:
            target = path.split("/contents/", 1)[1]
            if target in collision_paths:
                return httpx.Response(200, json={"sha": "existing"})
            return httpx.Response(404, json={"message": "Not Found"})
        if request.method == "POST" and path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": f"blob-sha-{len(calls)}"})
        if request.method == "POST" and path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "tree-sha"})
        if request.method == "POST" and path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": "new-commit-sha"})
        if request.method == "PATCH" and path.endswith("/git/refs/heads/master"):
            if state["patch_attempts"] < ff_fails:
                state["patch_attempts"] += 1
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            return httpx.Response(200, json={"object": {"sha": "new-commit-sha"}})
        if request.method == "GET" and "/compare/" in path:
            return httpx.Response(
                200,
                json={
                    "ahead_by": compare_ahead_by,
                    "behind_by": compare_behind_by,
                    "files": compare_files,
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    return handler


@pytest.fixture
def mock_client(monkeypatch):
    def _install(handler):
        monkeypatch.setattr(fk, "_client", lambda token: httpx.Client(transport=httpx.MockTransport(handler)))
    return _install


def _commit_post(**over):
    kwargs = dict(
        post_path="src/data/post/a-title.mdx",
        post_content=_POST_CONTENT,
        image_path="src/assets/images/a-title-hero.jpg",
        image_bytes=_IMAGE_BYTES,
        slug="a-title",
        title="A title",
    )
    kwargs.update(over)
    return fk.commit_post(**kwargs)


def test_happy_path_walks_the_full_sequence_with_an_additive_tree(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(_handler_sequence(calls))
    result = _commit_post()
    assert result == fk.CommitResult(commit_sha="new-commit-sha", post_url="https://feldklang.netlify.app/a-title")

    methods = [m for m, _u, _b in calls]
    assert methods == ["GET", "GET", "GET", "GET", "GET", "POST", "POST", "POST", "POST", "PATCH", "GET"]
    trees_call = next(b for m, u, b in calls if m == "POST" and u.endswith("/git/trees"))
    payload = json.loads(trees_call)
    assert payload["base_tree"] == "base-tree-sha"
    assert len(payload["tree"]) == 2
    assert {e["path"] for e in payload["tree"]} == {
        "src/data/post/a-title.mdx", "src/assets/images/a-title-hero.jpg",
    }
    assert all(e["mode"] == "100644" and e["type"] == "blob" and e["sha"] for e in payload["tree"])
    patch_call = next(b for m, u, b in calls if m == "PATCH")
    assert json.loads(patch_call) == {"sha": "new-commit-sha", "force": False}


def test_base_tree_omission_aborts_before_the_trees_post(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(_handler_sequence(calls))
    monkeypatch.setattr(fk, "_get_commit_tree_sha", lambda client, sha: "")
    with pytest.raises(fk.PublishError, match="base_tree"):
        _commit_post()
    assert not any(m == "POST" and u.endswith("/git/trees") for m, u, _b in calls)


def test_assert_additive_tree_rejects_empty_base_tree_directly():
    allowed = ("src/data/post/a.mdx", "src/assets/images/a-hero.jpg")
    entries = [
        {"mode": "100644", "type": "blob", "path": allowed[0], "sha": "s1"},
        {"mode": "100644", "type": "blob", "path": allowed[1], "sha": "s2"},
    ]
    with pytest.raises(fk.PublishError, match="base_tree"):
        fk._assert_additive_tree("", entries, allowed)


@pytest.mark.parametrize("slug", ["../etc", "foo/bar", "Foo", "", "a" * 81])
def test_bad_slugs_are_rejected_before_any_network_call(slug, monkeypatch):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")

    def boom(token):
        raise AssertionError("should not make a network call")

    monkeypatch.setattr(fk, "_client", boom)
    with pytest.raises(fk.PublishError):
        _commit_post(
            post_path=f"src/data/post/{slug}.mdx",
            image_path=f"src/assets/images/{slug}-hero.jpg",
            slug=slug,
        )


def test_a_mismatched_post_path_is_rejected_before_any_network_call(monkeypatch):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")

    def boom(token):
        raise AssertionError("should not make a network call")

    monkeypatch.setattr(fk, "_client", boom)
    with pytest.raises(fk.PublishError):
        _commit_post(post_path="package.json")


def test_collision_on_the_post_aborts_with_nothing_committed(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(_handler_sequence(calls, collision_paths=frozenset({"src/data/post/a-title.mdx"})))
    with pytest.raises(fk.PublishError, match="already exists"):
        _commit_post()
    assert not any(m == "POST" for m, _u, _b in calls)


def test_collision_on_the_image_aborts_with_nothing_committed(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(_handler_sequence(calls, collision_paths=frozenset({"src/assets/images/a-title-hero.jpg"})))
    with pytest.raises(fk.PublishError, match="already exists"):
        _commit_post()
    assert not any(m == "POST" for m, _u, _b in calls)


def test_non_fast_forward_retries_on_a_fresh_base_then_succeeds(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(_handler_sequence(calls, ff_fails=1))
    result = _commit_post()
    assert result.commit_sha == "new-commit-sha"
    patch_calls = [b for m, _u, b in calls if m == "PATCH"]
    assert len(patch_calls) == 2
    assert all(json.loads(b)["force"] is False for b in patch_calls)


def test_non_fast_forward_aborts_after_three_attempts_never_forcing(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(_handler_sequence(calls, ff_fails=999))
    with pytest.raises(fk.PublishError, match="fast-forward"):
        _commit_post()
    patch_calls = [b for m, _u, b in calls if m == "PATCH"]
    assert len(patch_calls) == fk._MAX_FF_RETRIES
    assert all(json.loads(b)["force"] is False for b in patch_calls)


def test_post_commit_check_flags_an_unexpected_extra_file(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(
        _handler_sequence(
            calls,
            compare_files=[
                {"filename": "src/data/post/a-title.mdx", "status": "added"},
                {"filename": "src/assets/images/a-title-hero.jpg", "status": "added"},
                {"filename": "README.md", "status": "modified"},
            ],
        )
    )
    with pytest.raises(fk.PublishError, match="unexpected files"):
        _commit_post()


def test_post_commit_check_flags_a_non_added_status(monkeypatch, mock_client):
    monkeypatch.setenv("FELDKLANG_GH_TOKEN", "t")
    calls: list = []
    mock_client(
        _handler_sequence(
            calls,
            compare_files=[
                {"filename": "src/data/post/a-title.mdx", "status": "modified"},
                {"filename": "src/assets/images/a-title-hero.jpg", "status": "added"},
            ],
        )
    )
    with pytest.raises(fk.PublishError, match="unexpected files"):
        _commit_post()


def test_missing_token_raises_not_configured_and_gh_token_does_not_substitute(monkeypatch):
    monkeypatch.delenv("FELDKLANG_GH_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "a-read-only-build-time-token")
    with pytest.raises(fk.PublishError, match="not configured"):
        _commit_post()
