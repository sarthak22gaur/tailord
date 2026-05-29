# agents/ — Source of Truth

This directory is the canonical home for **agents and rules** in **tailord**. The agent definitions in `.claude/`, `.codex/`, and `.opencode/` at the repo root are **generated** from here.

> **Skills are not managed here.** This repo ships its own skill pipeline
> (`tailord sync-skills`, source `src/tailord/skills/`) which owns
> `.claude/skills/`, `.codex/skills/`, `.opencode/skills/` and deletes anything
> it didn't generate. agentsync deliberately omits the skills layer so the two
> tools don't clobber each other. Project orientation therefore lives in the
> **Ground Truth** section of `agents/claude/CLAUDE.md` and `agents/AGENTS.md`,
> not in a ground-truth skill. To add a skill, edit `src/tailord/skills/` and
> run `tailord sync-skills`.

## Editing

1. Edit files in `agents/claude/`, `agents/codex/`, `agents/opencode/`, or `agents/claude/rules/`.
2. Run `bash agents/scripts/sync_agents.sh` to fan changes out to all surfaces.
3. Commit both `agents/` and the synced `.claude/` etc. directories.

## Layout

```
agents/
  AGENTS.md          # workspace overview (rendered to repo root)
  claude/
    CLAUDE.md        # Claude system prompt
    agents/          # Claude agent definitions (markdown)
    rules/           # Hard rules surfaced to Claude
  codex/
    agents/          # Codex agent TOMLs
    configs/         # Codex config fragments
  opencode/
    agents/          # OpenCode agent markdown
  scripts/           # Sync scripts
  # NB: no skills/ — skills are owned by `tailord sync-skills` (src/tailord/skills/)
```

## Never edit `.claude/`, `.codex/`, or `.opencode/` directly

They are regenerated on every sync. Your edits will be lost.

---

Generated with [agentsync](https://github.com/sarthak22gaur/agentsync).
