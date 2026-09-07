You are in the **Content Creation Team** area. Edit only files under
`dashboard/areas/content_creation_team/` and the shell listed in
`docs/AREAS.md`. Do not open any other `dashboard/areas/*` area, and do
not open the Job Application files
(`dashboard/_{documents,jobs,drafts,job_analysis,targeted_edit}.py`,
`dashboard/pages/{cover_letter_writer,cv_writer}.py`, their templates or
docs).

The capability is `content_creation_team` — import only its public names
(`run, Input, Output, Feedback, RevisionRound, Cost`), never `._core` /
`._contract`. The span editor here is a **self-contained copy**
(`_content_drafts.py` / `_content_targeted_edit.py` / `content_draft.html`
/ `static/content-draft-edit.js`), not the Job Application one.

A change that seems to need cross-area edits means the boundary is wrong
or the thing belongs in the shell — stop and ask.
