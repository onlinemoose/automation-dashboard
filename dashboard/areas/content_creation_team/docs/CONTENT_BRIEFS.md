# Content briefs

Write the **goal** and the **content brief** once, set the optional knobs
(length, house style, keywords…), then run the **content team** —
it researches, drafts, edits and SEO-reviews one finished piece. The
piece is saved on the brief; from there you fix a span or send it back to
the team for another round.

This is **the app's own storage** (CLAUDE.md rule 6): private to this
area, no capability sees it. The `content-creation-team` capability is
handed plain values and hands back one `Output`; the brief store keeps
the request and the result.

## The workflow

1. **Content briefs → New content brief** — a title, the goal, the brief.
2. The brief's page opens with the full knob form (goal, brief,
   `topic_areas`, `audience` / `audience_brief`,
   `target_length_words`, `call_to_action`, `target_keywords`,
   `house_style`, and — under "Operator limits" — `max_usd`,
   `max_editor_revisions`, `max_seo_revisions`). **Save brief** persists
   every field.
3. **Run the content team** (`POST /content/{id}/run`) — a streamed
   holding view while the pipeline runs (first runs are ~4 minutes; the
   contract has no progress callback, so it's a spinner, not a word
   count). On completion the finished **piece** is saved onto the brief
   and a **run summary** is appended to its history.
4. Once a brief has a saved piece, the brief detail page (`GET
   /content/{id}`) carries only the Briefing form + Save brief — no run
   panel, since a piece already exists. A file icon under the title (and
   in the `/content` list row, in place of the earlier unstyled "piece
   ready" text) opens the dedicated **piece page**
   (`GET /content/{id}/piece`, redirects to the brief detail page if no
   piece is saved yet): a **Publishing metadata** block (title / excerpt
   / slug / tags, with a "shipped without full approval" flag when
   `approved` is false), the editable **Final copy**, the read-only
   **SEO brief**, **Editor notes**, **SEO review notes**, **Research
   notes** and **Revision history** sections, plus **Send back to the
   content team**, **Run again from scratch**, and the **Run history**.
5. **Edit the piece two ways:**
   - **Edit draft** on the Final copy opens the span editor
     (`/content/drafts/{id}` — the same select → instruct → diff → accept
     flow as the Job Application drafts, on this area's own copy of that
     subsystem). **Save to brief** writes the edited copy back into the
     piece (and updates `piece.final_copy`, so a later send-back carries
     the edit).
   - **Send back to the content team** (`POST /content/{id}/send-back`) —
     one instruction per line (plus an optional quoted passage), re-runs
     `run()` with `previous_draft` + `previous_feedback` and the saved
     `research_notes` / `seo_brief`, so the research and SEO-brief stages
     don't repeat. The new piece replaces the old one; history grows.
   - **Run again from scratch** re-runs with no resume inputs.

## The capability seam — `content-creation-team`

`dashboard/areas/content_creation_team/_content_team.py` is the only file
that imports it (front door only: `run, Input, Output, Feedback,
RevisionRound, Cost`).

`Input` (required `goal`, `content_brief`; everything else optional):
`topic_areas: list[str]`, `audience`, `audience_brief`,
`target_length_words: int`, `call_to_action`, `target_keywords:
list[str]`, `house_style`; resume — `research_notes`, `seo_brief`,
`previous_draft`, `previous_feedback: list[Feedback]`; operator config —
`max_usd` (2.0), `max_editor_revisions` (5), `max_seo_revisions` (3).
`Feedback` is `(comment: str, quote: str | None)`.

The contract also has an optional `tone`, but the dashboard does **not**
surface it (v1 decision): in practice it overlapped with `house_style`
and the voice cues already inside the capability's stage prompts, and a
second free-text "voice" box just muddied the brief. Voice direction goes
in `house_style`. `build_input` never sets `tone`, so the capability
falls back to its own default (`None`).

`Output`: `final_copy` (Markdown), `title`, `excerpt`, `slug`,
`tags: list[str]`, `approved: bool`, `stopped_on`
(`approved` / `editor_budget` / `seo_budget` / `cost_cap`),
`research_notes`, `seo_brief`, `editor_notes`, `seo_notes`,
`revision_history: list[RevisionRound]`, `cost: Cost`.

## `house_style` is free text (v1 decision)

The DASHBOARD-SKETCH proposed a `doc_picker` backed by the Job
Application "Background documents" store. An area may not import another
area's module (`tests/test_guardrails.py::test_areas_do_not_cross_import`),
so `house_style` is a plain `textarea` persisted on the brief. If a
second area wants the same operator-config text, promote it to a
shell-level "style library" then.

The field's help text has an **"Insert the bundled default"** link that
fills the `textarea` with a vendored snapshot of the capability's default
house style
(`pages/_examples/content_creation_team/house_style_default.md`,
`DEFAULT_HOUSE_STYLE`), so an operator can trim it down instead of
writing one from scratch. The snapshot is not part of the contract and
drifts if the capability changes its default — the same caveat as the
demo `goal.md` / `brief.md` inputs.

## Storage

Two Supabase tables, service-role key, in-process-dict fallback when
`SUPABASE_URL` / `SUPABASE_SERVICE_KEY` are unset. DDL and the run-by-hand
process: `docs/migrations/2026-09-06_content_creation_team.sql`.

- **`content_briefs`** — the knob columns (all `not null default`, so the
  partial-merge `update_brief` needs no `_UNSET` sentinel; `target_length_words`
  0 and `max_usd` 2.0 are the "unset" values), plus `piece jsonb` (the
  finished piece — see below) and `runs jsonb` (append-only
  `{saved_at, stopped_on, approved, cost_usd, title}` summaries).
- **`content_drafts`** — a copy of the `drafts` table keyed to a nullable
  `content_brief_id` instead of `job_post_id`. Dedupe key
  `(user_id, slug, section, source_hash)`; undo is replay.

`piece` jsonb shape: `sections` (the rendered result sections),
`meta` (the 7 RunMeta fields), `saved_at`, and the raw Output fields a
send-back resumes from — `final_copy`, `research_notes`, `seo_brief`,
`title` / `excerpt` / `slug` / `tags`, `approved`, `stopped_on`, and a
`revision_history` **summary** (per-round verdicts + notes; the large
per-round `draft` text is dropped — the current `final_copy` supersedes it).

Rows are scoped per user: every store call takes the owning `user_id` and
every query filters on it, reads and writes alike (`docs/USER_SCOPING.md`).

## Configuration

`ANTHROPIC_API_KEY` (already at the app edge). Optional, read by the
capability from the environment — not form inputs, no `build_input`
involvement:

- `CONTENT_TEAM_FAST=1` — every stage on the cheapest model, no extended
  thinking, one web search. A wiring check, not a quality setting.
- `CONTENT_TEAM_{SEO_BRIEF,RESEARCHER,COPYWRITER,EDITOR,SEO_REVIEW}_MODEL`
  — per-stage model override.
- `CONTENT_TEAM_CACHE_TTL` — `5m` (default) or `1h`.

## No async in the routes

`run()` is a multi-minute synchronous call; the run route hands it to
`dashboard._streaming.stream_run`, which offloads it with
`run_in_threadpool` and keeps the connection warm. Store calls are
likewise wrapped in `run_in_threadpool`.
