# &lt;Capability&gt; — Contract

> Write this **before** building. If you can't fill in Inputs / Output
> without naming another module, the boundary is wrong — redraw it.

## Responsibility

One sentence. The single job this module does.

## Inputs — required

- `name` (type) — what it is, and where the caller gets it from

## Inputs — optional

- `name` (type, default) — what it adds when present. The module must
  still produce a valid result without it.

## Output

- `name` (type) — what it is, and what the caller does with it

## Out of scope

- Things this module deliberately does **not** do. Name them, so the
  boundary is explicit and nobody quietly widens it later.

## Storage

None.

_(Or: describe any storage that is private to this module. No other
module reads or writes it.)_

## Open questions

-
