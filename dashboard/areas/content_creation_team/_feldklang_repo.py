"""GitHub commit client for `onlinemoose/feldklang` — the app's own
outbound integration, and the layer seam the `publish-to-website`
capability must not cross (CLAUDE.md rule 2: "receives, returns, never
fetches"). The capability returns the `.mdx` post and the optimised hero
image; this module is the only thing in the system that ever pushes them
to a live repo.

One atomic, **additive-only** commit of both files to feldklang's
default branch (`master`), built directly against the Git Data API — no
git CLI, no local clone. Every guarantee below has a test in
`tests/test_content_publish.py`:

- `base_tree` is always set on the new tree, so every existing path in
  the repo carries over untouched (`_assert_additive_tree`).
- Only `src/data/post/<slug>.mdx` and `src/assets/images/<slug>-hero.jpg`
  can ever be written — never anything else (`_assert_writable`,
  `_assert_additive_tree`).
- No tree entry can carry `sha: null` (GitHub's delete-a-path op); no
  rename; the ref update is fast-forward-only and `force: true` is never
  sent.
- A pre-existing post or image aborts with no commit (`_check_no_collision`
  — there is no overwrite path anywhere in this module).
- The commit is verified after the fact (`_verify_commit`): if the diff
  isn't exactly the two files, both `added`, the run raises rather than
  letting the caller mark the piece as published.

Same backend-selection discipline as `_briefs.py`: the HTTP library is
imported lazily inside `_client`, and a module-level `threading.Lock`
serialises publishes in this process (most non-fast-forward races are a
different process publishing at the same instant; the lock only guards
against two requests inside this one).
"""

from __future__ import annotations

import base64
import os
import re
import threading
from dataclasses import dataclass

_OWNER = "onlinemoose"
_REPO = "feldklang"
_BRANCH = "master"
_POST_DIR = "src/data/post"
_IMAGE_DIR = "src/assets/images"
_API_BASE = f"https://api.github.com/repos/{_OWNER}/{_REPO}"
_DEFAULT_CANONICAL_BASE = "https://feldklang.netlify.app"

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SLUG_LEN = 80
_JPEG_MAGIC = b"\xff\xd8\xff"
_MAX_FF_RETRIES = 3

_lock = threading.Lock()


class PublishError(RuntimeError):
    """Every failure mode `commit_post` can hit: missing config, a bad
    slug/path, a collision, a non-fast-forward that couldn't be resolved,
    or a post-commit diff that doesn't match. The route turns this into a
    422/409 panel — never a silent no-op."""


@dataclass(frozen=True)
class CommitResult:
    commit_sha: str
    post_url: str


def reset() -> None:
    """No cached backend to drop — the token is read fresh on every call.
    Kept for symmetry with the area's other modules (`_briefs.reset()`)."""


# --- pre-flight: everything below runs before any network call ---------


def _validate_slug(slug: str) -> str:
    if not slug or not _SLUG_RE.match(slug) or len(slug) > _MAX_SLUG_LEN:
        raise PublishError(
            f"Invalid slug {slug!r} — lowercase letters, digits and single "
            "hyphens only, no leading/trailing/doubled hyphen, ≤80 characters."
        )
    return slug


def _target_paths(slug: str) -> tuple[str, str]:
    """The only two paths a publish may ever write, recomputed from the
    validated slug — never trusted from the caller's arguments."""
    slug = _validate_slug(slug)
    return f"{_POST_DIR}/{slug}.mdx", f"{_IMAGE_DIR}/{slug}-hero.jpg"


def _assert_writable(path: str, allowed: tuple[str, str]) -> str:
    """`path` must be exactly one of the two recomputed targets, and must
    not smuggle a traversal or control characters."""
    if ".." in path.split("/") or path.startswith("/") or "//" in path:
        raise PublishError(f"Refusing to write unsafe path {path!r}.")
    if any(ord(c) < 0x20 for c in path):
        raise PublishError(f"Refusing to write a path with control characters: {path!r}.")
    if path not in allowed:
        raise PublishError(
            f"Refusing to write {path!r} — not one of the two publish targets {allowed!r}."
        )
    return path


def _assert_artefacts(post_content: str, image_bytes: bytes) -> None:
    if not post_content.startswith("---\n") or "\n---" not in post_content[4:]:
        raise PublishError(
            "post_content doesn't look like a frontmatter'd .mdx file "
            "(missing the opening/closing '---' delimiters)."
        )
    if not image_bytes or not image_bytes.startswith(_JPEG_MAGIC):
        raise PublishError("image_bytes is empty or not a JPEG (missing the FF D8 FF magic).")


def _token() -> str:
    # Deliberately not a GH_TOKEN fallback: that token is read-only and
    # scoped for pulling private capability repos at build time (see
    # render.yaml) — reusing it here would either fail confusingly or,
    # if ever broadened, conflate a read token with a write one.
    token = os.environ.get("FELDKLANG_GH_TOKEN")
    if not token:
        raise PublishError(
            "Publishing is not configured — FELDKLANG_GH_TOKEN is not set."
        )
    return token


# --- the Git Data API sequence ------------------------------------------


def _client(token: str):
    """Lazy import, like `_briefs._SupabaseBackend`. The single seam a
    test replaces to inject an `httpx.MockTransport`."""
    import httpx

    return httpx.Client(
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )


def _url(path: str) -> str:
    return f"{_API_BASE}{path}"


def _assert_2xx(resp, what: str):
    if resp.status_code // 100 != 2:
        raise PublishError(f"{what} failed: {resp.status_code} {resp.text[:300]}")
    return resp


def _get_default_branch(client) -> None:
    resp = _assert_2xx(client.get(_url("")), "GET feldklang repo")
    branch = resp.json().get("default_branch")
    if branch != _BRANCH:
        raise PublishError(
            f"feldklang's default_branch is {branch!r}, not {_BRANCH!r} — "
            "refusing to publish against the wrong branch."
        )


def _get_ref_sha(client) -> str:
    resp = client.get(_url(f"/git/ref/heads/{_BRANCH}"))
    if resp.status_code == 404:
        raise PublishError(f"Branch heads/{_BRANCH} not found on feldklang.")
    _assert_2xx(resp, f"GET git/ref/heads/{_BRANCH}")
    return resp.json()["object"]["sha"]


def _get_commit_tree_sha(client, commit_sha: str) -> str:
    resp = _assert_2xx(client.get(_url(f"/git/commits/{commit_sha}")), "GET git/commits")
    tree_sha = (resp.json().get("tree") or {}).get("sha")
    if not tree_sha:
        raise PublishError(f"Commit {commit_sha} has no tree sha.")
    return tree_sha


def _check_no_collision(client, post_path: str, image_path: str) -> None:
    for path in (post_path, image_path):
        resp = client.get(_url(f"/contents/{path}"), params={"ref": _BRANCH})
        if resp.status_code == 200:
            slug = path.rsplit("/", 1)[-1]
            raise PublishError(
                f"{path} already exists in feldklang — publish under a new slug "
                f"(no overwrite; got {slug!r})."
            )
        if resp.status_code != 404:
            raise PublishError(f"GET contents {path} failed: {resp.status_code} {resp.text[:300]}")


def _create_text_blob(client, text: str) -> str:
    resp = _assert_2xx(
        client.post(_url("/git/blobs"), json={"content": text, "encoding": "utf-8"}),
        "POST git/blobs (post)",
    )
    return resp.json()["sha"]


def _create_binary_blob(client, data: bytes) -> str:
    resp = _assert_2xx(
        client.post(
            _url("/git/blobs"),
            json={"content": base64.b64encode(data).decode("ascii"), "encoding": "base64"},
        ),
        "POST git/blobs (image)",
    )
    return resp.json()["sha"]


def _assert_additive_tree(base_tree_sha: str, entries: list[dict], allowed: tuple[str, str]) -> None:
    """Every guarantee a tree-creation payload must hold before it is
    ever sent: a `base_tree` (so existing paths carry over untouched),
    exactly the two allowed paths, `100644` blobs only, and never an
    empty sha (GitHub's delete-a-path op)."""
    if not base_tree_sha:
        raise PublishError(
            "Refusing to build a tree without base_tree — would replace the whole repo."
        )
    if len(entries) != 2:
        raise PublishError(f"Expected exactly 2 tree entries, got {len(entries)}.")
    for entry in entries:
        path = entry.get("path")
        if path not in allowed:
            raise PublishError(f"Refusing to write {path!r} — outside the publish targets.")
        if entry.get("mode") != "100644" or entry.get("type") != "blob":
            raise PublishError(f"Refusing to write a non-100644/non-blob entry for {path!r}.")
        if not entry.get("sha"):
            raise PublishError(f"Refusing to write {path!r} with an empty sha — no deletes, ever.")


def _create_tree(client, base_tree_sha: str, entries: list[dict], allowed: tuple[str, str]) -> str:
    _assert_additive_tree(base_tree_sha, entries, allowed)
    resp = _assert_2xx(
        client.post(_url("/git/trees"), json={"base_tree": base_tree_sha, "tree": entries}),
        "POST git/trees",
    )
    return resp.json()["sha"]


def _create_commit(client, message: str, tree_sha: str, parent_sha: str) -> str:
    resp = _assert_2xx(
        client.post(
            _url("/git/commits"),
            json={"message": message, "tree": tree_sha, "parents": [parent_sha]},
        ),
        "POST git/commits",
    )
    return resp.json()["sha"]


def _update_ref(client, new_sha: str) -> bool:
    """True on a fast-forward success; False on a 422 non-fast-forward
    (the caller re-reads the ref and retries); raises on anything else.
    `force` is always explicitly False — never sent as True."""
    resp = client.patch(_url(f"/git/refs/heads/{_BRANCH}"), json={"sha": new_sha, "force": False})
    if resp.status_code == 200:
        return True
    if resp.status_code == 422:
        return False
    raise PublishError(f"PATCH git/refs/heads/{_BRANCH} failed: {resp.status_code} {resp.text[:300]}")


def _verify_commit(client, base_sha: str, new_sha: str, post_path: str, image_path: str) -> None:
    """Post-commit sanity check: the diff must be exactly the two files,
    both `added`. Any deviation means the commit already landed but
    something is wrong — detect-and-alarm (raise) rather than silently
    marking the piece as published."""
    resp = client.get(_url(f"/compare/{base_sha}...{new_sha}"))
    if resp.status_code != 200:
        raise PublishError(
            f"Commit {new_sha} landed on feldklang but the post-commit diff check "
            f"failed to run ({resp.status_code}) — publish flagged, not saved."
        )
    data = resp.json()
    if data.get("ahead_by") != 1 or data.get("behind_by") != 0:
        raise PublishError(
            f"Commit {new_sha} landed on feldklang but ahead_by/behind_by was "
            f"{data.get('ahead_by')}/{data.get('behind_by')} (expected 1/0) — "
            "publish flagged, not saved."
        )
    files = data.get("files") or []
    allowed = {post_path, image_path}
    bad = [f for f in files if f.get("filename") not in allowed or f.get("status") != "added"]
    if len(files) > 2 or bad:
        raise PublishError(
            f"Commit {new_sha} landed on feldklang but touched unexpected files "
            f"({[f.get('filename') for f in files]!r}) — publish flagged, not saved."
        )


def commit_post(
    *,
    post_path: str,
    post_content: str,
    image_path: str,
    image_bytes: bytes,
    slug: str,
    title: str,
    canonical_base: str = _DEFAULT_CANONICAL_BASE,
) -> CommitResult:
    """One atomic, additive commit of both files to feldklang's default
    branch. No `overwrite` parameter exists anywhere in this module — a
    pre-existing post or image always aborts with nothing committed."""
    validated_post_path, validated_image_path = _target_paths(slug)
    allowed = (validated_post_path, validated_image_path)
    if post_path != validated_post_path or image_path != validated_image_path:
        raise PublishError(
            f"post_path/image_path don't match the slug's canonical targets "
            f"({validated_post_path!r}, {validated_image_path!r})."
        )
    _assert_writable(validated_post_path, allowed)
    _assert_writable(validated_image_path, allowed)
    _assert_artefacts(post_content, image_bytes)

    token = _token()
    message = f"Add post: {title}\n\nPublished via the automation dashboard's Content Creation Team area."

    with _lock, _client(token) as client:
        _get_default_branch(client)
        base_sha = _get_ref_sha(client)

        for _attempt in range(_MAX_FF_RETRIES):
            base_tree_sha = _get_commit_tree_sha(client, base_sha)
            _check_no_collision(client, validated_post_path, validated_image_path)

            post_blob = _create_text_blob(client, post_content)
            image_blob = _create_binary_blob(client, image_bytes)
            tree_sha = _create_tree(
                client,
                base_tree_sha,
                [
                    {"mode": "100644", "type": "blob", "path": validated_post_path, "sha": post_blob},
                    {"mode": "100644", "type": "blob", "path": validated_image_path, "sha": image_blob},
                ],
                allowed,
            )
            commit_sha = _create_commit(client, message, tree_sha, base_sha)

            if _update_ref(client, commit_sha):
                _verify_commit(client, base_sha, commit_sha, validated_post_path, validated_image_path)
                return CommitResult(
                    commit_sha=commit_sha,
                    post_url=f"{canonical_base}/{slug}",
                )
            # Non-fast-forward: the branch moved under us. Re-read and
            # retry on the new base — never retry with force=True.
            base_sha = _get_ref_sha(client)

        raise PublishError(
            f"Could not fast-forward heads/{_BRANCH} after {_MAX_FF_RETRIES} attempts "
            "— the branch kept moving under us. Nothing was left committed on it "
            "(the dangling blob/tree/commit objects are GC'd by GitHub)."
        )
