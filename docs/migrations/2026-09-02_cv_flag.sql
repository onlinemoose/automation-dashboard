-- 2026-09-02 — mark which background documents are CVs
--
-- Intent: additive, non-destructive. Adds a boolean `is_cv` to
-- `background_documents` so the writer pages can offer CVs in the
-- "Load a saved CV" picker and keep everything else in the
-- background-notes checklist.
--
-- Run BY HAND in the Supabase SQL editor. Nothing in the app executes
-- this file; it is kept here as the record of what was applied and how to
-- reverse it.
--
-- Backfill decision: every row that exists today is a CV (the store has
-- only ever held pasted-in CVs), so the column is added with default
-- TRUE — which backfills every existing row to TRUE — and the default is
-- then flipped to FALSE so a new document is a background note unless the
-- "This document is a CV" box is ticked.

-- ============================ FORWARD ============================

alter table background_documents
  add column is_cv boolean not null default true;

alter table background_documents
  alter column is_cv set default false;

-- ============================ ROLLBACK ============================
-- alter table background_documents drop column is_cv;
