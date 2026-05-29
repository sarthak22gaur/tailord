# Plan Before Code (Hard Rule)

Before any non-trivial implementation:

1. Produce or read an approved plan. Trivial = single-file fix, typo, formatting, isolated bug with obvious cause. Everything else needs a plan.
2. The plan is authored by the architect agent (or by the user) and lives in `workspace/plans/` or in the ticket/PR body.
3. The user must approve the plan before implementation starts.
4. Engineers execute the plan; they do not author it.

## Why

- Surfaces design ambiguity before code is written.
- Gives the user a checkpoint to redirect cheaply.
- Produces a written contract that code reviews can check against.

## When to ask for a plan

- Multi-file changes.
- Cross-module or cross-repo work.
- New abstractions, interfaces, or schemas.
- Anything affecting external API surface.

When in doubt, ask the user whether a plan is needed before starting.
