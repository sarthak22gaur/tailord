# Changelog

All notable changes to tailord are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning is
[SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `tailord import <path>` can draft `data/master.yaml` from an existing
  `.txt`, `.md`, or `.pdf` resume using the configured model runner, with
  schema validation and raw-output debug files for invalid model output.
- Local LLM usage accounting: bridge jobs persist token/cost columns in
  `<vault>/.tailord/jobs.db`, CLI runner calls append
  `<vault>/.tailord/events.jsonl`, and `tailord stats` reports average,
  median, p95, cache hit rate, and optional kind/model/CSV breakdowns.

## [0.1.0] — initial public release

First release. The framework / vault split, the agent skills, the
browser bridge, the multi-tool skill sync, and the documented CLI
surface are all considered stable for v0.1.

### Added
- **Vault / framework split.** Your career data lives in a vault
  directory you own; the framework is upgradable independently.
  Vault discovery via `RESUME_VAULT` env var, `.resumerc.yaml` in CWD
  or any ancestor, or `$XDG_CONFIG_HOME/tailord/config.yaml`.
- **`tailord` CLI.** `init`, `validate`, `doctor`, `install-browsers`,
  `build`, `cover`, `preview`, `score-job`, `sync-skills`, `setup-bridge`,
  `serve`.
  `--vault PATH` works as a top-level override on any subcommand.
- **JSON-Schema validation** for `master.yaml`, every variant,
  `user-preferences.yaml`, and cover-letter variants.
- **Resume + cover-letter rendering** via Jinja templates and headless
  Chromium. Deterministic, single-page, with an auto page-fit pass.
- **Agent skills** (`resume-job-fit-evaluator`, `resume-tailoring`,
  `cover-letter-writing`, `resume-bullet-writing`,
  `resume-evidence-review`) as Markdown with YAML frontmatter, parameterized
  by `data/user-preferences.yaml` at runtime.
- **Multi-client skill sync.** Single source at
  `src/tailord/skills/<name>/SKILL.md`; `tailord sync-skills` writes
  per-client output dirs (`.claude/skills/`, `.codex/skills/`,
  `.opencode/skills/`) that ship in git for clone-and-go discovery. CI
  enforces no-drift with `--check`.
- **`ModelRunner` protocol** with `claude_cli` and `anthropic_api`
  implementations for the Python `score-job` command. The API runner
  marks the system prompt cacheable so batch scoring is cheap.
- **Browser bridge + extension** (`tools/jd-bridge/`,
  `tools/jd-extension/`). Fastify HTTP server, SQLite-backed job
  queue, MV3 extension with a LinkedIn DOM adapter. JD → tailored
  resume + cover-letter PDFs in one click.
- **`tailord setup-bridge`** scaffolds `tools/jd-bridge/.env` with a
  random `BRIDGE_TOKEN` + resolved vault/framework paths, then runs
  `npm install`.
- **Bridge state in the vault.** SQLite job history at
  `<vault>/.tailord/jobs.db` so it travels with the user's data, not
  the framework checkout. No env-var override on purpose.
- **`FORBIDDEN_TOKENS` guard** in the renderer — populate via
  `RESUME_FORBIDDEN_TOKENS` env var to hard-fail PDF builds when a
  banned substring slips into rendered output.
- **CI**: editable-install job (validate + render every variant) plus
  a wheel-install job that builds a wheel, installs it into a clean
  venv, asserts framework data ships, and runs `tailord init`
  end-to-end. `sync-skills --check` enforced on every push.
- **Sample vault** at `src/tailord/examples/sample-vault/` (fictional
  "Jane Doe") shipped inside the wheel. `tailord init` scaffolds from
  this.
- Docs: `README.md`, `POSITIONING.md`, `docs/quickstart.md`,
  `docs/vault-anatomy.md`, `docs/skills.md`, `docs/model-runners.md`,
  `docs/privacy.md`, `docs/advanced/extension.md`.

### Known limitations
- **Distribution**: v0.1.0 is git+https only. PyPI publish is planned
  once the install flow is validated by real users.
- **`anthropic_api` runner in the bridge worker**: not implemented.
  The bridge spawns the `claude` CLI for the full tool-use pipeline.
  Python `tailord score-job --runner anthropic_api` works for
  scoring-only flows without the CLI.
- **`tailord tailor-job`**: deferred. Use the bridge or run `claude`
  interactively with the `resume-tailoring` skill.
- **Site adapters**: LinkedIn only. Adding another site is a single
  adapter file (see `tools/jd-extension/content/adapters/`).
- **Browser extension**: sideloaded only. Not on the Chrome Web Store
  or AMO.

[Unreleased]: https://github.com/sarthak22gaur/tailord/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/sarthak22gaur/tailord/releases/tag/v0.1.0
