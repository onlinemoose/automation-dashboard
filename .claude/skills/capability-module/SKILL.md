---
name: capability-module
description: Scaffold and enforce the rules for a discrete, standalone capability module in Python — one job, one public front door, clear typed inputs and outputs, no orchestration framework inside, contract written first. Use when the user is starting, building, or reviewing a capability/module meant to work in isolation and be composed into larger workflows later.
---

# Building a Capability Module

A **capability module** is one discrete piece of functionality — one job,
clear inputs, a clear output — that works in isolation and is composed
into larger workflows later without the module itself changing.

The template is on GitHub at
`https://github.com/onlinemoose/capability-module-template` (and locally
at `/Users/markus/Code/capability-module-template`). A repo made from it
carries its own `CLAUDE.md` with these same rules.

## Starting a new module

1. **Name the one job in a single sentence.** If it needs two unrelated
   sentences, it is two modules — split it before going further.
2. **Make a new repo from the template.** Preferred: on GitHub, "Use
   this template" to create `<name>`, then clone it — the new repo has
   its own fresh history. Locally instead: copy the template folder,
   then delete `.git` in the copy and `git init`. Either way, leave the
   inner `capability/` package named as-is — do not rename it, and do
   not touch the import lines in `cli.py` or `tests/`. Each module is
   its own project, so the package name never clashes.
3. **Write `docs/CONTRACT.md` before implementing** — Responsibility,
   Inputs (required then optional), Output, Out of scope, Storage. If it
   can't be written without naming another module, the boundary is
   wrong; stop and redraw it with the user.
4. **Fill in `capability/_contract.py`** with the real input/output
   fields, then **implement `capability/_core.py`.** Keep `run()` in
   `capability/__init__.py` as the only public entry point.
5. **Verify in isolation:** `uv run python cli.py --help`,
   `uv run pytest`, `uv run lint-imports`.
6. **Add the first real `docs/PROGRESS.md` entry.**

## The rules — enforce on every change

1. **One front door.** `run(...)` is the only public entry point;
   everything else in the package is internal.
2. **Receives, returns — never fetches.** All inputs are arguments to
   `run(...)`; the result is returned. No reading other systems'
   databases, no calling other modules. The only outbound calls are to
   the LLM the module uses internally.
3. **No shared storage.** Any persistence is private to this module.
4. **Describable in isolation.** State the inputs and output without
   naming another module.
5. **Contract before code.** `docs/CONTRACT.md` is agreed first.
6. **One reason to change.** A requirement change lands only in this
   repo.
7. **Optional inputs, not dependencies.** Extra context is an optional
   argument with a default; the module works without it.
8. **No orchestration framework.** Never add `prefect` / `dagster` /
   `airflow` / `celery`; `uv run lint-imports` enforces this.

## Releasing a change

The module is consumed by an orchestrator as a pinned git dependency
(`... @ git+…@vX.Y.Z`). After a change: tests + `lint-imports` pass →
bump `version` in `pyproject.toml` (**patch** = prompt tweak/fix,
**minor** = new optional input, **major** = `CONTRACT.md` changed so
callers break) → `docs/PROGRESS.md` entry → commit → `git tag vX.Y.Z` →
push the tag. Do not reach into the orchestrator; it moves its own pin.

## Reviewing an existing module

Walk the eight rules in order. The most common breakage: `run()`, or
code it calls, reaching out to fetch its own inputs instead of receiving
them as arguments. Flag it and propose lifting that fetch up into the
caller (the orchestration layer).
