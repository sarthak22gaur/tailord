# tailord — Claude Rules

Local, evidence-backed job-application workbench: renders YAML resume + cover-letter facts into deterministic PDFs, scores job descriptions against a local evidence corpus, and ships a browser extension + local bridge that evaluates a LinkedIn job then generates tailored documents on request — all driven by your local Claude Code (`claude` CLI). Nothing leaves the machine except the model calls Claude Code makes.

Languages: Python (CLI + render/score pipeline), JavaScript/Node (browser extension + bridge). Default base branch: `main`.

---

## Skill Discipline

Read the **Ground Truth** section below first for orientation, then consult the project's own skills under `src/tailord/skills/` (resume-tailoring, cover-letter-writing, resume-evidence-review, etc.) when the task they cover applies. Those skills are the house style for resume/cover work — follow them literally. "MUST" is a hard constraint. Apply rules to every file you touch, not just the first. Do not invent project rules.

> Note: the resume/cover skills are owned by `tailord sync-skills` (source: `src/tailord/skills/`, fanned out to `.claude/skills/`, `.codex/skills/`, `.opencode/skills/`). agentsync deliberately does **not** write into those dirs. To add or edit a product skill, edit the source and run `tailord sync-skills` — not the agentsync sync.

---

## Ground Truth

The single source of truth for project orientation. (Kept here rather than in a skill because `tailord sync-skills` owns the skills dirs.)

### What it is
A laptop-local job-application workbench. YAML resume facts → deterministic PDFs (Jinja + Playwright), matching cover letters, JD scoring against a local evidence corpus, plus a Chrome extension + local Node bridge that evaluates a LinkedIn job and generates tailored docs on demand. The only network egress is the model calls the local `claude` CLI makes.

### Layout (single repo)
- `src/tailord/` — the Python package (CLI, render/score pipeline, skills source).
- `src/tailord/skills/` — **source** of the resume/cover skills; synced to `.{claude,codex,opencode}/skills/` by `tailord sync-skills`.
- `src/tailord/templates/`, `src/tailord/schemas/` — Jinja PDF templates and the JSON Schemas for the YAML vault.
- `src/tailord/examples/sample-vault/` — sample vault shipped in the wheel; CI validates + renders it.
- `tools/jd-bridge/` — local Node HTTP server bridging the extension to the `claude` CLI.
- `tools/jd-extension/` — Chrome MV3 extension (LinkedIn → evaluate → generate).
- `tests/` — pytest (bridge packaging + runtime). `docs/` — user docs. `jobs/generated/` — per-job tailored output (gitignored).

### Primary stack
- **Python ≥3.11**: CLI and rendering/scoring. Deps: pyyaml, jinja2, jsonschema, pypdf; `[pdf]` extra adds playwright.
- **JavaScript/Node ≥20.6**: extension + bridge only.

### Entry points
- CLI: `tailord.cli:main` — `src/tailord/cli.py:869`. Subcommands: init, validate, doctor, install-browsers, build, cover, preview, setup-bridge, serve, score-job, stats, import, lint, sync-skills, tailor-job (deferred).
- Resume render: `src/tailord/render.py:406`. Cover render: `src/tailord/cover_letter.py:193`. Validation: `src/tailord/validate.py:336`. Bullet lint: `src/tailord/lint_bullets.py:128`. Skill sync: `src/tailord/sync_skills.py:201`.
- Vault facts: `data/master.yaml` + `data/variants/*.yaml` + `data/cover-letter-variants/*.yaml` (the vault lives outside the repo at the path `RESUME_VAULT` / `--vault` points to; `src/tailord/examples/sample-vault/` is the in-repo reference copy).

### Conventions
- Base branch `main`. `tailord` is the documented public CLI surface (v0.1.0+); `resume-*` console scripts are legacy one-shots.
- CI (`.github/workflows/ci.yml`) enforces: `tailord validate`, HTML render of every variant, and **`tailord sync-skills --check`** (fails on any unexpected file under `.{claude,codex,opencode}/skills/`).
- Generated output dirs (`.claude/`, `.codex/`, `.opencode/`) are **committed** to git (a clean clone ships them) — agentsync's `OUTPUT_TRACKING=all` matches this.

### What this is not
Live code behaviour or the current bug list. For those, read the code or the relevant doc.

---

## Available Agents

- `/architect` — design authority, produces plans
- `/code-reviewer` — plan-driven code review
- `/librarian` — keeps `agents/` in sync with reality
- `/engineer` — feature and bug implementation

## Hard Rules

See `.claude/rules/` for binding constraints. The non-negotiable ones:
- `no-commit-attribution.md` — no AI attribution in commits or PRs
- `plan-before-code.md` — plan + approval before non-trivial implementation
