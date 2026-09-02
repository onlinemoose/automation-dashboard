-- 2026-09-02 — link a working draft back to the job post it came from
--
-- Intent: additive, non-destructive. Adds a nullable `job_post_id` to
-- `drafts` so the draft editor's "Save to job post" button can write the
-- edited text back into that job post's `cover_letter` / `tailored_cv`
-- result slot. NULL for a draft opened from a result with no job post
-- behind it (the button is hidden then).
--
-- Run BY HAND in the Supabase SQL editor. Nothing in the app executes
-- this file; it is kept here as the record of what was applied and how to
-- reverse it.
--
-- Backfill decision: none. Existing drafts predate the link and stay
-- NULL; re-opening one from its result panel stamps the id (the store
-- backfills a NULL `job_post_id` on `create_or_get`).

-- ============================ FORWARD ============================

alter table drafts
  add column job_post_id uuid references job_posts(id) on delete set null;

create index if not exists drafts_job_post_id_idx on drafts (job_post_id);

-- ============================ ROLLBACK ============================
-- drop index if exists drafts_job_post_id_idx;
-- alter table drafts drop column job_post_id;
