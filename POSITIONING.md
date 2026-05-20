# POSITIONING

The positioning doc the rest of the genericization work reads from. Locked
decisions live here; the README, schemas, and CLI all reference back to this.

## What this is

`tailord` is a **local, evidence-backed job-application workbench**.

You keep your career facts — work history, project specifics, links to the
documents that prove your claims — in a private vault on your machine. The
framework gives you:

- **Resume rendering** — YAML → PDF via Jinja + Playwright.
- **Cover-letter generation** — same pipeline, voice rules per user.
- **JD fit scoring** — agent reads a job description and scores it against
  vault facts plus your hard constraints (visa, geo, role targets).
- **Tailoring loop** — agent produces a job-specific variant, citing evidence
  from the vault. No fabricated claims.
- **Browser bridge** — queue JDs from a job page, get a tailored PDF + cover
  letter as a desktop notification.

The whole stack runs on your machine. Nothing leaves the box except the LLM
API call.

## What it isn't

- **Not a SaaS competitor to Teal / Jobscan.** Those are hosted, ATS-keyword
  optimizers. This is the opposite: bring your own facts, keep them local,
  let agents tailor against an evidence corpus you control.
- **Not a resume *generator*.** It will not invent experience for you. The
  agent is constrained to facts in `data/master.yaml` and the linked
  evidence corpus.
- **Not a LinkedIn scraper.** The extension extracts the JD on the page you
  are already looking at — the same content you would copy-paste. No bulk
  crawling, no API abuse.
- **Not a "for anyone" tool.** v1 targets technical job-seekers comfortable
  with YAML, git, and Claude. The wizard scaffolds a vault; you still have
  to fill it.

## Target user

The narrow person v1 serves:

- Engineer / PM / data person actively job-hunting.
- Comfortable editing YAML, running CLIs, reading PDFs.
- Has more than one "version" of their resume already (e.g. infra vs
  platform vs startup) — the pain that motivates the variant system.
- Privacy-leaning: does not want their career history in another SaaS DB.
- Willing to bring their own Claude credentials (Anthropic API key or
  `claude` CLI on the same machine).

If two of those don't apply, this isn't the tool yet.

## Public surface area for v1

**CLI-first.** The first thing a stranger touches is:

```
pipx install 'tailord[pdf] @ git+https://github.com/sarthak22gaur/tailord.git'
tailord install-browsers
tailord init ~/resume-vault
tailord build
```

The browser extension is the **power-user path**, documented in
`docs/advanced/extension.md`. It is not in the README hero. The bridge is an
implementation detail of the extension path and is not pitched as a
standalone product.

## The vault contract

Two repos, clear ownership boundary:

**Framework** — `tailord` (public, MIT):

- `src/tailord/` — installable Python package (CLI, renderers, validators).
- `src/tailord/templates/` — Jinja + CSS.
- `src/tailord/skills/` — generic `SKILL.md` files, parameterized by user-preferences.
- `src/tailord/schemas/` — versioned JSON Schema for every vault file.
- `src/tailord/examples/sample-vault/` — fictional candidate; CI builds against this.
- `tools/jd-bridge/`, `tools/jd-extension/` — the power-user path (Node + browser, not pip-installed).

**Vault** — user-owned (private repo or just a local dir):

- `data/master.yaml` — the one source of truth.
- `data/variants/*.yaml` — resume tailoring variants.
- `data/cover-letter-variants/*.yaml`.
- `data/user-preferences.yaml` — visa, geo, role targets, voice.
- `docs/resume-research/` — evidence corpus.
- `jobs/generated/` — per-JD outputs (gitignored).
- `output/` — rendered PDFs.

The framework upgrades freely; the vault is the user's forever.

## Naming (locked)

| Thing | Name |
| --- | --- |
| Project name | `tailord` (kept; the broader workbench framing lives in the pitch, not the name) |
| Env var | `RESUME_VAULT` |
| Config file | `.resumerc.yaml` (CWD or any ancestor, git-style discovery) |
| User-config dir | `$XDG_CONFIG_HOME/tailord/` |
| CLI entrypoint | `tailord` |

## Non-goals for v1

- No hosted version.
- No LinkedIn API integration.
- No multi-user or team features.
- No "AI rewrites your bullets" — evidence-only tailoring.
- No Windows-first support. Works on macOS + Linux; Windows is best-effort.

## Tagline

**Tailor every resume against your real evidence — locally.**

## Open questions deferred

- License: MIT. This is a personal project with no plans for monetization, so the permissive route wins over reserving a hosted-SaaS option. (Earlier drafts considered FSL-1.1-Apache-2.0 to reserve a commercial offering; dropped as unnecessary.)
- npm / Docker packaging for the bridge — decide in P6.
- Anonymous telemetry — ship without it; revisit only if there's a reason.
