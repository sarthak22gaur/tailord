# tailord

Local, evidence-backed job-application workbench: renders YAML resume + cover-letter facts into deterministic PDFs, scores job descriptions against a local evidence corpus, and ships a browser extension + local bridge that evaluates a LinkedIn job then generates tailored documents on request — all driven by your local Claude Code (`claude` CLI). Nothing leaves the machine except the model calls Claude Code makes.

## Workspace

- Languages: Python (CLI + render/score pipeline), JavaScript/Node (browser extension + bridge)
- Default base branch: `main`
- Repo shape: single

## Agents

| Agent | Role |
|---|---|
| architect | Design authority — plans, ADRs, system boundaries |
| code-reviewer | Plan-driven review against project conventions |
| librarian | Keeps `agents/` source-of-truth in sync with reality |
| engineer | Implements features and fixes |

## Ground Truth

The single source of truth for project orientation. (Kept here, not in a skill, because the repo's own `tailord sync-skills` owns the skills dirs.)

- **What it is**: a laptop-local job-application workbench. YAML resume facts → deterministic PDFs (Jinja + Playwright), matching cover letters, JD scoring against a local evidence corpus, plus a Chrome extension + local Node bridge (LinkedIn → evaluate → generate). Only egress is the local `claude` CLI's model calls.
- **Layout**: `src/tailord/` (Python package — CLI, render/score, skills source); `src/tailord/templates/` + `schemas/` (Jinja PDF templates, JSON Schemas); `src/tailord/examples/sample-vault/` (CI-validated sample); `tools/jd-bridge/` (Node HTTP bridge to the `claude` CLI); `tools/jd-extension/` (Chrome MV3 extension); `tests/` (pytest); `docs/`; `jobs/generated/` (per-job output, gitignored).
- **Stack**: Python ≥3.11 (CLI + pipeline; pyyaml/jinja2/jsonschema/pypdf, `[pdf]`→playwright). Node ≥20.6 (extension + bridge only).
- **Entry points**: CLI `tailord.cli:main` (`src/tailord/cli.py:869`; subcommands init/validate/doctor/build/cover/preview/serve/score-job/import/lint/sync-skills/…). Render `render.py:406`, cover `cover_letter.py:193`, validate `validate.py:336`, skill sync `sync_skills.py:201`.
- **Vault**: `data/master.yaml` + `data/variants/*.yaml` + `data/cover-letter-variants/*.yaml`, at the path `RESUME_VAULT`/`--vault` points to.

## Product Skills (owned by the repo, not agentsync)

The repo distributes its own skills (resume-tailoring, cover-letter-writing, resume-evidence-review, resume-importing, resume-job-fit-evaluator, resume-bullet-writing) from `src/tailord/skills/` via `tailord sync-skills`. agentsync does **not** write into the skills dirs. Edit those skills at the source and run `tailord sync-skills`.

## Conventions

- No AI attribution in commits or PR bodies.
- Plan before code: architect plan + user approval before non-trivial implementation.
- Source of truth for agents is `agents/`. Edit there, then run `bash agents/scripts/sync_agents.sh`.
- CI enforces `tailord validate` and `tailord sync-skills --check`. Generated surface dirs (`.claude/`, `.codex/`, `.opencode/`) are committed to git.
