# capability-module-template

A starting point for building **one discrete capability** as a standalone
Python project — something with clear inputs and a clear output that is
useful on its own, and can be plugged into larger workflows later without
the capability itself changing.

Examples: "write a cover letter", "assess fit for a role", "summarise a
job posting". Each one is its own repository created from this template.

The rules every capability must follow are in **`CLAUDE.md`**, which
Claude Code reads automatically inside any repository created from this
template — so the constraints travel with the code and you don't have to
restate them.

---

## One-time setup on this machine

You need two things installed:

- **VS Code** with the Claude Code extension (you already have this).
- **`uv`** — the tool that runs the Python. Check by opening a terminal
  (in VS Code: **Terminal → New Terminal**) and typing `uv --version`.
  If that errors, install it: `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Making a new capability

### 1. Make a new repo from this template

**On GitHub (preferred).** Go to
<https://github.com/onlinemoose/capability-module-template>, click
**Use this template → Create a new repository**, name it for the
capability (e.g. `cover-letter-writer`), and create it. The new repo
starts with its own fresh history — no leftover link to the template.
Then clone it to your Mac.

*(One-time: the "Use this template" button only appears if the
template repo's **Settings → Template repository** box is ticked.)*

Leave the inner `capability/` folder named exactly as it is. Nothing to
rename inside; no code to edit by hand.

### 2. Open the new project in VS Code

**File → Open Folder**, pick your new `cover-letter-writer` folder.

### 3. Write the contract — `docs/CONTRACT.md`

This is the part that's yours, and it's product work, not code. Open
`docs/CONTRACT.md` and fill in every section:

- **Responsibility** — the one job, in a sentence.
- **Inputs (required / optional)** — what it needs to be handed.
- **Output** — what it gives back.
- **Out of scope** — what it deliberately does *not* do.

The test: if you can't describe the inputs and output without naming
another capability, the boundary is wrong. Sort that out before moving
on.

### 4. Have Claude Code build it

Start Claude Code in VS Code and say something like:

> This is a new capability module. Read `CLAUDE.md` and
> `docs/CONTRACT.md`, then fill in `capability/_contract.py` and
> implement `capability/_core.py` to match the contract.

Claude follows the rules in `CLAUDE.md` automatically. Review what it
produces against your contract.

### 5. Check it works on its own

In the VS Code terminal:

```
uv run python cli.py --input examples/sample.txt   # try it end to end
uv run pytest                                       # does it honour the contract?
uv run lint-imports                                 # did anything forbidden sneak in?
```

Replace `examples/sample.txt` with a real input to feel whether the
output is actually good.

### 6. Log it — `docs/PROGRESS.md`

Add a dated line saying what the module now does. Future-you (and Claude)
read this first.

---

## When is it done?

When step 5's three commands pass **and** a real input produces output
you'd actually use. At that point the capability stands on its own. Wiring
several capabilities together into a single experience is a separate,
later job — and an easy one, because each piece has a clean contract.

---

## Shipping changes later

Once an orchestrator uses this capability, it does so by pinning a git
tag, so every change worth picking up is a tagged release:

1. Make the change; `uv run pytest` and `uv run lint-imports` pass.
2. Bump `version` in `pyproject.toml` — **patch** for a prompt tweak or
   fix, **minor** for a new optional input, **major** if `CONTRACT.md`
   changed in a way that breaks existing callers.
3. Add a `docs/PROGRESS.md` entry, commit, then `git tag vX.Y.Z` and
   push the tag.

The orchestrator picks it up when *it* chooses to move its pin — nothing
here reaches into it. Full detail is in `CLAUDE.md` → "Releasing a new
version".

---

## Optional: make the skill available everywhere

`.claude/skills/capability-module/` is a Claude skill that walks through
this process and can review an existing module against the rules. It
works inside repositories created from this template already. To use it
in *any* project:

```
cp -R .claude/skills/capability-module ~/.claude/skills/
```
