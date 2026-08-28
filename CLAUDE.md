# CLAUDE.md — Capability Module

This repo is **one capability module**: a single, discrete piece of
functionality with clear inputs and a clear output (e.g. "write a cover
letter", "assess fit for a role", "summarise a job posting"). It is
built to work in isolation first, and be composed into larger workflows
later — without the module itself changing.

> **Part of a larger system.** Read the architecture overview first —
> `automation-architecture/ARCHITECTURE.md` (sibling repo; a link once
> published) — for how capabilities, orchestration, and the dashboard
> fit together, and which rules are system-wide vs. specific to this
> repo.

> **New copy of the template?** Do these, then delete this note:
> 1. Write `docs/CONTRACT.md` before touching `_core.py`.
> 2. Fill in the real inputs/outputs in `capability/_contract.py`.
> 3. Implement `capability/_core.py`.
>
> Leave the `capability/` folder name exactly as it is — nothing to
> rename, no import lines to change. Each module is its own project, so
> the name never clashes.

## Mental model

A capability module is a contractor hired for one task. It has a
job-order form — *given these inputs, return this output* — and it never
wanders into other contractors' workshops or reads their files.

## The layers — and where this repo sits

- **Capability module** ← *this repo*. One job. Plain Python.
- **Orchestration** — a separate layer, elsewhere, that calls modules in
  sequence and passes their outputs along. Prefect, or an AI that
  decides which module to call, lives there. **Never in this repo.**
- **Experience** — UI, CLI, chat. Talks to orchestration, never reaches
  into a module.

## Rules — do not break these

1. **One front door.** `capability.run(...)` is the only public entry
   point. Everything else in the package is internal — prefix names with
   `_`, or keep them out of `__init__.py`.
2. **Receives, returns — never fetches.** Every input arrives as an
   argument to `run(...)`. The result is returned. The module never
   reaches out to get data itself: no reading another system's database,
   no calling another module, no network calls except to the LLM it uses
   internally.
3. **No shared storage.** If the module persists anything, that storage
   is private to it and described in `docs/CONTRACT.md`. No other module
   reads or writes it.
4. **Describable in isolation.** State the inputs and output without
   naming another module. "Takes a job posting and a CV, returns a cover
   letter" ✅. "Takes the Insights module's output" ❌.
5. **Contract before code.** `docs/CONTRACT.md` is written and agreed
   before the implementation changes. If it can't be written without
   referencing another module, the boundary is wrong — stop and redraw.
6. **One reason to change.** A requirement change lands in this repo
   only. If a change here forces a change elsewhere, the contract was
   wrong.
7. **Optional inputs, not dependencies.** Richer context (a prior draft,
   a pre-computed analysis) may be an *optional* argument with a
   default. The module must still produce a valid result without it.
8. **No orchestration framework.** Do not add `prefect` (or `dagster`,
   `airflow`, `celery`) as a dependency. `uv run lint-imports` enforces
   this.

## Structure

```
capability/            the module package — keep this name; nothing to rename
  __init__.py          exposes run(), Input, Output — nothing else is public
  _contract.py         the input/output shapes ("types" = the written shape of the data)
  _core.py             internal implementation, organised however you like
cli.py                 run the module in isolation from a terminal
docs/
  CONTRACT.md          the input/output spec — the product artifact; write it first
  PROGRESS.md          dated log, newest entry on top
tests/
  test_run.py          proves run() honours the contract
examples/
  sample.txt           a real input, so cli.py works end to end immediately
```

Managed with `uv` (`uv run ...`, `uv add ...`). Any LLM calls use the
`anthropic` SDK and are an internal detail of `_core.py`.

## Running it in isolation

```
uv run python cli.py --help
uv run python cli.py --input examples/sample.txt > out.md
```

If `run(...)` can't produce anything useful without another module's
output, the boundary is wrong.

## Checking the guardrails

```
uv run lint-imports        # fails if the module imports an orchestration framework
uv run pytest              # fails if run() breaks the contract
```

## Releasing a new version

The orchestrator consumes this repo as a **pinned git dependency**
(`... @ git+https://…/<repo>.git@vX.Y.Z`), so every change other projects
should pick up is a tagged release:

1. Make the change; `uv run pytest` and `uv run lint-imports` pass.
2. Bump `version` in `pyproject.toml`, using what changed as the guide:
   - **patch** (0.2.0 → 0.2.1) — prompt tweak or fix; inputs/outputs unchanged.
   - **minor** (0.2.0 → 0.3.0) — new *optional* input, or better output;
     existing callers unaffected.
   - **major** (0.2.0 → 1.0.0) — the contract in `docs/CONTRACT.md`
     changed (a required input added, output shape changed); callers
     must update their code to match.
3. Add a `docs/PROGRESS.md` entry.
4. Commit, then `git tag vX.Y.Z` and push the tag.

Nothing here reaches into the orchestrator. It upgrades on its own
schedule by moving its pin to the new tag.

## Plugging into orchestration — not this repo's concern

Something outside imports `capability.run` and calls it — directly, or
wrapped as a Prefect task, or exposed as an AI tool / MCP server. None of
that changes this repo. The module never knows which is happening.

The orchestrator is its own separate project. Its build/deploy details
(Dockerfile, `uv.lock`, `uv sync --frozen`, upgrading a pinned
capability, rollback) live *there*, not in this template.
