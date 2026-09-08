-- 2026-09-06 — Content Creation Team area: two app-owned tables
--
-- Intent: additive, non-destructive. Adds the stores for the new
-- `dashboard/areas/content_creation_team/` area:
--   * `content_briefs`  — a goal + brief + the optional knobs, and the
--     finished piece (jsonb `piece`) once the content team has run, plus
--     append-only run summaries (jsonb `runs`).
--   * `content_drafts`  — the area's own working-draft store for span
--     edits of the "Final copy" (a copy of `drafts`, keyed to a
--     `content_brief_id` instead of a `job_post_id`).
--
-- Run BY HAND in the Supabase SQL editor. Nothing in the app executes
-- this file. Both stores fall back to an in-process dict when
-- SUPABASE_URL / SUPABASE_SERVICE_KEY are unset, so local dev and the
-- test suite need nothing.
--
-- Backfill decision: none — a new area, no existing rows.

-- ============================ FORWARD ============================

create table content_briefs (
  id                   uuid primary key default gen_random_uuid(),
  title                text not null,
  goal                 text not null,
  content_brief        text not null,
  topic_areas          text not null default '',   -- one tag per line
  audience             text not null default '',
  audience_brief       text not null default '',
  target_length_words  integer not null default 0, -- 0 == unset
  call_to_action       text not null default '',
  target_keywords      text not null default '',   -- one keyword per line
  house_style          text not null default '',
  max_usd              real not null default 2.0,
  max_editor_revisions integer not null default 5,
  max_seo_revisions    integer not null default 3,
  piece                jsonb,                       -- finished piece; NULL until first run
  runs                 jsonb not null default '[]', -- append-only run summaries
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  user_id              uuid not null references auth.users(id) on delete cascade
);
create index if not exists content_briefs_user_id_idx on content_briefs (user_id);
grant all privileges on table content_briefs to service_role;
alter table content_briefs enable row level security;

create table content_drafts (
  id               uuid primary key default gen_random_uuid(),
  slug             text not null,   -- always 'content-creation-team'
  section          text not null,   -- Output-section slug, e.g. 'final-copy'
  source_hash      text not null,   -- sha256 of the normalised original
  original         text not null,   -- immutable
  current          text not null,   -- original + accepted revisions
  revisions        jsonb not null default '[]',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  user_id          uuid not null references auth.users(id) on delete cascade,
  content_brief_id uuid references content_briefs(id) on delete set null,
  unique (user_id, slug, section, source_hash)
);
create index if not exists content_drafts_user_id_idx          on content_drafts (user_id);
create index if not exists content_drafts_content_brief_id_idx on content_drafts (content_brief_id);
grant all privileges on table content_drafts to service_role;
alter table content_drafts enable row level security;

-- ============================ ROLLBACK ============================
-- drop table if exists content_drafts;
-- drop table if exists content_briefs;
