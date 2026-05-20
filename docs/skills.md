# Skills

`src/tailord/skills/` is the **single source of truth** for every skill —
Markdown instructions for the LLM agent that does the reasoning, not the
renderer. Each `SKILL.md` carries YAML frontmatter with `name` and
`description`.

Per-client output directories at the repo root are **generated** from the
source by `tailord sync-skills`:

```
src/tailord/skills/<name>/SKILL.md     ← source of truth (edit this)
.claude/skills/<name>/SKILL.md         ← generated (Claude Code)
.codex/skills/<name>/SKILL.md          ← generated (Codex)
.opencode/skills/<name>/SKILL.md       ← generated (OpenCode)
```

The generated dirs are committed to git so a fresh clone works with any
supported runtime without an extra setup step. CI runs `sync-skills
--check` on every push to prevent drift.

> **Editing a skill?** Edit *only* the file under `src/tailord/skills/`,
> then run `tailord sync-skills`, then commit both the source change and
> the regenerated output dirs together.

The framework ships five skills:

| Skill | When the agent uses it |
| --- | --- |
| [resume-job-fit-evaluator](../src/tailord/skills/resume-job-fit-evaluator/SKILL.md) | User asks "is this worth applying to?" — produces a scorecard. |
| [resume-tailoring](../src/tailord/skills/resume-tailoring/SKILL.md) | User asks to apply / tailor — produces `variant.yaml` + `notes.md` + rendered PDF. |
| [cover-letter-writing](../src/tailord/skills/cover-letter-writing/SKILL.md) | User wants a cover letter for a JD — produces `cover-letter.yaml` + rendered PDF. |
| [resume-bullet-writing](../src/tailord/skills/resume-bullet-writing/SKILL.md) | House style for bullet text — used by tailoring whenever it rewrites or adds a bullet. |
| [resume-evidence-review](../src/tailord/skills/resume-evidence-review/SKILL.md) | Trust rules for the evidence corpus — used whenever a bullet draws from `docs/resume-research/`. |

## How user-preferences flow into the skills

The first three skills explicitly read `data/user-preferences.yaml` at
runtime. The framework doesn't hard-code candidate-specific assumptions
in skill prose; they live in your vault and the skills reference them by
field name.

| Skill | Reads | Effect |
| --- | --- | --- |
| job-fit-evaluator | `work_authorization.requires_sponsorship` | If true, JDs that forbid sponsorship are gated to "No-go". |
| job-fit-evaluator | `targets.roles`, `targets.anti_roles` | Compatibility cap when a JD lands in `anti_roles`. |
| resume-tailoring | `work_authorization.requires_sponsorship` | Step-0 gate stops tailoring on explicit-no JDs. |
| resume-tailoring | `evidence_corpus_dir` | Where to look for trusted research docs. |
| cover-letter-writing | `cover_letter.voice.description` | Voice guide. |
| cover-letter-writing | `cover_letter.voice.forbidden_phrases` | Banned phrases. |
| cover-letter-writing | `cover_letter.length.{min_words,max_words}` | Renderer warns to stderr if outside bounds. |

If a field is missing from `user-preferences.yaml`, the skill falls back
to neutral behavior (no gate, no cap, sensible defaults). You can run the
framework with no `user-preferences.yaml` at all — the skills just won't
filter anything.

## Editing skills

Skills are framework code, not vault content. Editing them gives every
JD a different reasoning shape — useful for changing the rubric, the
output format, or the trust rules. If you find yourself wanting to
change skill prose to encode something candidate-specific, that's a
signal it should be a field in `user-preferences.yaml` instead.

## Invoking skills outside the bridge

The skills work in any skill-aware runtime:

- **Claude Code CLI** auto-discovers `.claude/skills/<name>/SKILL.md` from
  the repo root. `cd` into a `git clone` of tailord and ask "score this
  JD" — the CLI loads the skill via its frontmatter description.
- **Codex** auto-discovers `.codex/skills/<name>/SKILL.md`. Same flow.
- **OpenCode** auto-discovers `.opencode/skills/<name>/SKILL.md`.
- **Anthropic API direct**: paste a skill's full `SKILL.md` into the
  system prompt. The CLI's `score-job` subcommand does exactly this — see
  `src/tailord/cli.py`.

The skills are intentionally LLM-runtime-agnostic. They're plain English
with a couple of structured contracts (the `RESULT:` line for the bridge,
the YAML shapes for variants and cover letters).

## Adding a client

`tailord sync-skills` writes one SKILL.md per (skill, client) pair under
`.<client>/skills/<name>/`. To add a fourth client:

1. Add the client name to the `CLIENTS` tuple in
   `src/tailord/sync_skills.py`.
2. Re-run `tailord sync-skills` and commit the new output dir.
3. If the new client expects a different frontmatter shape, extend
   `_render_skill_md` with per-client transformations.

If a client wants a single concatenated prompt instead of per-skill files
(some lightweight runtimes do), produce that as a separate `_render_*`
function and write it alongside the per-skill files.
