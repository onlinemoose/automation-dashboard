You are in the **Content Creation Team** area. Edit only files under
`dashboard/areas/content_creation_team/` and the shell listed in
`docs/AREAS.md`. Do not open any other `dashboard/areas/*` area, and do
not open the Job Application files
(`dashboard/_{documents,jobs,drafts,job_analysis,targeted_edit}.py`,
`dashboard/pages/{cover_letter_writer,cv_writer}.py`, their templates or
docs).

The capabilities are `content_creation_team` (import only its public
names — `run, Input, Output, Feedback, RevisionRound, Cost` — never
`._core` / `._contract`) and `publish_to_website` (same rule: `run,
Input, Output, Cost` only, via `_publish.py`). The span editor here is a
**self-contained copy** (`_content_drafts.py` / `_content_targeted_edit.py`
/ `content_draft.html` / `static/content-draft-edit.js`), not the Job
Application one.

**Publish to website** (`/content/{brief_id}/publish`) is this area's
outbound write to a live repo, not a capability call: `_publish.py`
adapts a brief's finished piece into a `publish_to_website.Input`;
`_feldklang_repo.py` is the area-owned GitHub commit client that pushes
the returned `.mdx` + hero image to `onlinemoose/feldklang` (Git Data
API, additive-only, no overwrite — see its module docstring and
`docs/CONTENT_BRIEFS.md`). Both are area-owned; neither is a capability
front door itself.

A change that seems to need cross-area edits means the boundary is wrong
or the thing belongs in the shell — stop and ask.
