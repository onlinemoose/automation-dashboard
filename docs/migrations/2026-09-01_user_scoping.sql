-- 2026-09-01 — per-user scoping for the app's own stores
--
-- Intent: additive. Adds a `user_id` column to each of the three
-- app-owned tables (`background_documents`, `job_posts`, `drafts`), makes
-- the `drafts` uniqueness key per-user, and indexes `user_id` on each.
--
-- Run BY HAND in the Supabase SQL editor. Nothing in the app executes
-- this file; it is kept here as the record of what was applied and how to
-- reverse it.
--
-- !! DESTRUCTIVE STEP !! The forward script begins with a `truncate` of
-- all three tables. This is deliberate (the decision was: no backfill —
-- existing rows have no owner and are deleted rather than assigned one).
-- The rollback script below CANNOT restore truncated rows. Take a backup
-- first if any row matters.
--
-- The dropped constraint name `drafts_slug_section_source_hash_key` was
-- confirmed against `pg_constraint` by hand before this was run.

-- ============================ FORWARD ============================

truncate table drafts, job_posts, background_documents;

alter table background_documents
  add column user_id uuid not null references auth.users(id) on delete cascade;
alter table job_posts
  add column user_id uuid not null references auth.users(id) on delete cascade;
alter table drafts
  add column user_id uuid not null references auth.users(id) on delete cascade;

-- drafts uniqueness is now per-user
alter table drafts drop constraint drafts_slug_section_source_hash_key;
alter table drafts add constraint drafts_user_slug_section_source_hash_key
  unique (user_id, slug, section, source_hash);

create index if not exists background_documents_user_id_idx on background_documents (user_id);
create index if not exists job_posts_user_id_idx            on job_posts (user_id);
create index if not exists drafts_user_id_idx               on drafts (user_id);

-- ============================ ROLLBACK ============================
-- Drops only what the forward script added (the column, the swapped
-- constraint, the indexes). It does NOT — and cannot — restore the rows
-- removed by the `truncate` above.

-- alter table drafts drop constraint drafts_user_slug_section_source_hash_key;
-- alter table drafts add constraint drafts_slug_section_source_hash_key
--   unique (slug, section, source_hash);
-- drop index if exists background_documents_user_id_idx;
-- drop index if exists job_posts_user_id_idx;
-- drop index if exists drafts_user_id_idx;
-- alter table background_documents drop column user_id;
-- alter table job_posts            drop column user_id;
-- alter table drafts               drop column user_id;
