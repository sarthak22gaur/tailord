# Quickstart

10-minute walk-through from zero to a rendered resume PDF.

## 1. Install

Requirements:

- Python 3.11+
- `pipx` (or `pip install` inside a venv)
- For PDF rendering: a Chromium install (handled by `tailord install-browsers`)
- For `import` / `score-job` / the extension: [Claude Code](https://docs.claude.com/en/docs/claude-code)
  (the `claude` CLI) on `$PATH`. This is the path tailord uses; an
  `ANTHROPIC_API_KEY`-based runner exists but is untested (see step 6).

```bash
# Direct from GitHub (v0.1.0). The extra goes before the @ in this
# direct-reference form; keep the whole spec quoted because it contains [].
pipx install 'tailord[pdf] @ git+https://github.com/sarthak22gaur/tailord.git'
tailord install-browsers
```

If you want to hack on the framework itself, do an editable clone install:

```bash
git clone https://github.com/sarthak22gaur/tailord.git
cd tailord
pip install -e '.[pdf]'
tailord install-browsers
```

A PyPI release (`pipx install tailord`) is planned once the install flow
has been validated by a few real users.

Verify:

```bash
tailord --help
tailord doctor
```

`doctor` prints the resolved vault, framework root, and a checklist for
the `claude` CLI, Playwright module, Chromium browser, and `ANTHROPIC_API_KEY`.
Before you create a vault it reports that validation is skipped; after
`tailord init`, it runs the validator at the end.

## 1.5 Import an existing resume (optional)

If you already have a resume, use it as the fast path instead of hand-writing
`data/master.yaml` from scratch:

```bash
tailord init ~/resume-vault
cd ~/resume-vault
tailord import ~/Downloads/old-resume.pdf --force
tailord validate
```

`tailord import` accepts `.pdf`, `.txt`, and `.md` files, or `-` for pasted
stdin text. It writes a draft `data/master.yaml`; review it like any generated
first pass before building.

## 2. Scaffold a vault

```bash
tailord init ~/resume-vault
```

The wizard asks for name / email / location / sponsorship and copies the
fictional sample vault into `~/resume-vault`. A `.resumerc.yaml` is
written there so the rest of the CLI knows where to look.

```
~/resume-vault/
├── .resumerc.yaml
├── data/
│   ├── master.yaml
│   ├── user-preferences.yaml
│   ├── variants/{master,ai_platform,infra,startup}.yaml
│   └── cover-letter-variants/{master,ai_platform,infra,startup}.yaml
├── docs/resume-research/      ← your evidence corpus (start empty)
├── jobs/generated/            ← per-JD outputs land here
├── output/                    ← rendered PDFs land here
└── README.md
```

## 3. Edit `data/master.yaml`

This is your real work history. The wizard substituted the name fields
but everything else is fictional ("Acme Labs", "Globex Corp"). Replace
bullets, IDs, dates, skills with your own.

Schema cheatsheet:

```yaml
profile:
  name: Your Name
  email: you@example.com

experience:
  - id: globex                       # stable id; referenced by variants
    company: Globex Corp
    role: Senior Software Engineer
    start: March 2022
    end: Present
    bullets:
      - id: globex_workflow_engine   # stable id; referenced by variants
        priority: 100                # higher = appears earlier
        tags: [platform, backend]
        text: >-
          Designed and led a **distributed workflow engine** ...
```

The full schema lives in
[`src/tailord/schemas/master.schema.yaml`](../src/tailord/schemas/master.schema.yaml). Run
`tailord validate` after each edit.

## 4. Edit `data/user-preferences.yaml`

This is what makes the skills work for *you*. Fields:

- `work_authorization.requires_sponsorship` — gate that lets the
  job-fit evaluator filter no-sponsorship JDs.
- `targets.{roles, anti_roles, geo, seniority}` — role-family fit gate.
- `cover_letter.{voice, forbidden_phrases, length}` — applied to every
  cover letter the renderer produces.

See [`src/tailord/schemas/user-preferences.schema.yaml`](../src/tailord/schemas/user-preferences.schema.yaml).

## 5. Render

```bash
tailord build --variant master
# → ~/resume-vault/output/<your-name>_master.pdf

tailord cover --variant master
# → ~/resume-vault/output/<your-name>_cover_letter_master.pdf

tailord build --all   # every static variant
```

Hot-reload preview during edits:

```bash
tailord preview --variant master
# → http://127.0.0.1:8000 — refreshes on save
```

## 6. Score a JD

```bash
cat > acme-jd.txt <<'EOF'
Acme Corp is hiring a Senior Platform Engineer to build distributed systems,
operate Python and TypeScript services, and improve reliability.
EOF

# Uses your local `claude` CLI (the default runner).
tailord score-job ./acme-jd.txt
```

The output is a markdown scorecard with compatibility / consideration
scores, a requirement matrix, and an apply / skip recommendation.

> There is also an `--runner anthropic_api` path that calls the Anthropic API
> directly (install the `[api]` extra and set `ANTHROPIC_API_KEY`), but it is
> **untested** — the supported path is the local `claude` CLI. See
> [model-runners.md](model-runners.md).

## Next

- **Browser extension + bridge** — the recommended LinkedIn job-page workflow;
  see [advanced/extension.md](advanced/extension.md).
- **Privacy / data flow** — see [privacy.md](privacy.md).
- **What every file in a vault means** — see [vault-anatomy.md](vault-anatomy.md).
