# Working drafts — targeted revision

A capability result is usually close but not right. Instead of re-running
the whole writer, open a result section as a **working draft** and change
it in place: type directly into it, or revise one span at a time (select
a sentence, say what to change, and only that sentence is rewritten).
Then download it.

This is **the app's own storage** (CLAUDE.md rule 6): private to the
dashboard, no capability sees it. The `targeted-editor` capability is
handed only `{document, selection, instruction, kind}` and returns a
replacement for the span; the splice, the history, and undo are the
app's. A manual edit is recorded the same way — one revision, the whole
span replaced — so it shows in History and `Undo last` reverts it.

## The workflow

1. On a result page, click **Edit draft** under a section. That `POST`s
   the section's Markdown to `/drafts`, which creates (or re-finds) a
   working draft and opens the editor at `/drafts/{id}`. Only sections a
   page marks `editable` carry the button — the primary output (the
   letter, the CV), not a read-only "What it targeted" note.
2. **Select** any run of text in the draft. A floating **Revise…** button
   appears.
3. Type an **instruction** ("make this concrete", "drop the second
   sentence", "less breathless") and **Propose revision**.
4. The proposal is shown as a **word-level diff** plus a one-line note
   and the run cost. **Accept** splices it into the draft; **Reject**
   discards it; **Retry** re-asks with the same span (optionally an
   amended instruction).
5. Or just **type into the draft** — it's editable text, not a read-only
   view. The change autosaves (on blur, or first if you hit Download or
   Undo before that fires) as one revision (instruction `(manual edit)`).
6. **Undo last** drops the most recent revision — a span accept or a
   manual edit alike. **Download .md** saves what's on screen.

Only one edit is in flight at a time — while a span proposal is open, the
draft is briefly locked (not directly editable) and new selections are
ignored, until it's accepted, rejected, or cancelled.

## Where it lives

| Piece | File |
|---|---|
| Store (the only module that talks to Supabase) | `dashboard/_drafts.py` |
| The splice + undo-by-replay | `apply_revision()` / `replay()` in `dashboard/_drafts.py` |
| Capability adapter | `dashboard/_targeted_edit.py` |
| Screens | `/drafts*` routes in `dashboard/app.py`, `templates/draft.html`, `static/draft-edit.js` |
| Entry point | the "Edit draft" button in `templates/_result_panel.html`, per `Section` where `editable` is true |

`/drafts`, `/drafts/{draft_id}`, `/drafts/{draft_id}/revise`,
`/drafts/{draft_id}/accept`, `/drafts/{draft_id}/undo`,
`/drafts/{draft_id}/edit`, `/drafts/{draft_id}/download` are app-native
routes — not capability pages. `tests/test_guardrails.py` lists them in `ALLOWED_ROUTES` for that
reason, the same category as `/jobs` and `/documents`.

## The revision is a capability

Rewriting a span so it satisfies an instruction and still fits the
surrounding voice is LLM domain logic, so it lives in its own capability
module — **`targeted-editor`** (imported as `targeted_editor`) — consumed
here like `job-analyst`. It is composed at an allowed seam (CLAUDE.md
rule 5): the `/drafts/{id}/revise` handler reads the draft's `current`
text from the app's store, calls `targeted_editor.run(...)`, and renders
the returned span as a diff. On accept, `/drafts/{id}/accept` writes it
back to the store.

```python
# dashboard/_targeted_edit.py
import targeted_editor

def revise(document, selection, instruction, *, kind="prose") -> Revision:
    out = targeted_editor.run(targeted_editor.Input(
        document=document, selection=selection, instruction=instruction, kind=kind))
    return Revision(revised=out.revised, note=out.note, cost=_cost(out.cost))
```

**What `targeted-editor` returns**, and how it's used:

```python
Input(document: str, selection: str, instruction: str, kind: str = "prose")
      # kind: "prose" | "cover_letter" | "cv" — a light register steer
Output(revised: str, note: str, cost: Cost)
      # revised: the replacement for `selection` ONLY — never the whole document
```

- **`kind`** is derived from the Output-section slug by
  `_targeted_edit.kind_for_section()` — `"cover-letter" → "cover_letter"`,
  `"cv" → "cv"`, anything else → `"prose"`.
- **`revised`** already has the selection's own leading/trailing
  whitespace re-attached by the capability, so the splice can't weld
  words together.
- **`cost`** maps field-for-field onto the `RunMeta` footer
  (`capability="targeted-editor"`).
- The capability raises `ValueError` for bad input and `RuntimeError` if
  the model returned the whole document or the span unchanged; the
  `/revise` route turns both into a `422` with the message.

### Local dev / release pin

`targeted-editor` is tagged `v0.1.0` but not yet pushed, so
`pyproject.toml` overrides it to a path:
`targeted-editor = { path = "../targeted-editor", editable = true }` (a
sibling checkout). Once the repo is on GitHub, swap that for
`{ git = "https://github.com/onlinemoose/targeted-editor.git", rev = "v0.1.0" }`,
`uv lock`, and add a `docs/PROGRESS.md` entry.

## The draft model

```sql
create table drafts (
  id           uuid primary key default gen_random_uuid(),
  slug         text not null,          -- the capability page that produced it
  section      text not null,          -- the Output section, e.g. "cover-letter"
  source_hash  text not null,          -- sha256 of the original run output
  original     text not null,          -- as run() first produced it — never mutated
  current      text not null,          -- original + every accepted revision, in order
  revisions    jsonb not null default '[]',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  unique (user_id, slug, section, source_hash)
);

create index if not exists drafts_user_id_idx on drafts (user_id);

grant all privileges on table drafts to service_role;
alter table drafts enable row level security;
```

- **One draft per `(user_id, slug, section, source_hash)`** — re-opening the
  same result returns the same working draft (`create_or_get_draft`), and
  two users opening the same text get two independent drafts. The `unique`
  constraint backs that. `create_or_get` scopes its lookup as well as
  stamping the insert: miss the lookup half and the second user re-uses the
  first's draft, revisions and all.
- **`original` is immutable.** It's kept for "reset" and for showing how
  far the draft has drifted.
- **Undo is replay.** Each `revisions` entry records the `span_start` /
  `span_len` it was applied at (offsets into `current` at that moment).
  To undo, drop the last entry and recompute `current` from `original` +
  the remaining entries, applying each splice in order — the recorded
  offsets reproduce exactly because every edit was taken against the
  freshly-updated `current` (one edit at a time, accept before the next).
  Linear history only.

Uses `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` (already declared for
Background documents and Job posts). If either is missing, `_drafts.py`
uses a process-local dict and emits a `warnings.warn` — nothing persists
across a restart. Fine for local dev and tests.

## `slug` / `section` / `text` are app-storage keys

The `POST /drafts` body carries the producing page's `slug`, the Output
`section` slug, and that section's `text` — all app-storage keys, not a
capability `Input`. The capability only ever sees `document` (the current
draft), `selection`, `instruction`, and `kind`.

## Notes / limits

- **Per-user scoped.** Every query filters on `user_id`, reads and writes
  alike, and each public function takes the owning user's id as its last
  required argument (`create_or_get_draft(slug, section, text, user_id)`,
  `get_draft(draft_id, user_id)`,
  `record_revision(draft_id, user_id, *, …)`,
  `undo_last(draft_id, user_id)`). Every draft route already 404s on a
  `None` fetch, so **another user's draft returns 404, not 403** — the
  route can't distinguish "no such draft" from "not yours", and doesn't
  try. See `USER_SCOPING.md` and
  `migrations/2026-09-01_user_scoping.sql`.
- **One span edit in flight.** New selections are ignored, and the doc is
  briefly not directly editable, while a span proposal is open. No batch
  review, no multiple pending spans.
- **Manual edit is a full-span replace.** Typing into the `<pre>` and
  letting it save records the whole new draft as one revision
  (`instruction = "(manual edit)"`, `span_start = 0`,
  `span_len = len(current)`), spliced by the same `apply_revision` /
  `replay`. It is *not* the deferred whole-draft AI mode below — no
  capability call, just the user's own text.
- **The `<pre>` is `contenteditable`, with Enter and paste intercepted.**
  Left to the browser, Enter in a contenteditable reaches for a `<div>` /
  `<br>` — an element, not a `"\n"` character — which `textContent` drops
  or splits with no separator, desyncing the span-selection offsets.
  `draft-edit.js` inserts the character itself via a `Range`, and does
  the same for a paste (plain text only, HTML formatting stripped). A
  change autosaves on blur, or is flushed first if Download or Undo is
  used before that fires — either always acts on what's on screen. This
  choice was deliberate: it reuses the existing Range-based
  selection-offset code for the span-revision flow untouched, rather than
  swapping the `<pre>` for a `<textarea>`, which has no equivalent API for
  positioning the floating **Revise…** button at a text selection.
- **Raw Markdown, not rendered.** The editor shows the draft as source in
  a `<pre>` so selection offsets map 1:1 to the stored text with no
  DOM-range-to-source mapping. A "preview rendered" toggle is a later
  add.
- **Download only.** Saving an edited draft back to a Job post or other
  downstream reuse is deferred.
- **Whole-draft feedback is a separate mode** (deferred): an instruction
  with no selection that re-runs the original writer with the
  instruction folded in.
- **No async.** The revise call is synchronous, wrapped in
  `run_in_threadpool` like the writer `run()`.
