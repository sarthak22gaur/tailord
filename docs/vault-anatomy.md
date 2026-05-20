# Vault anatomy

What every file under a vault means, with the schema and the rules each
must satisfy. The framework reads from these files; nothing here is
auto-generated.

A vault is just a directory. Keep it in a private git repo, or just on
disk — your choice.

```
<vault>/
├── .resumerc.yaml             ← (optional) discovery hint
├── data/
│   ├── master.yaml            ← canonical resume facts
│   ├── user-preferences.yaml  ← visa, targets, cover-letter voice
│   ├── variants/
│   │   ├── master.yaml        ← static resume variants
│   │   ├── ai_platform.yaml
│   │   ├── infra.yaml
│   │   └── startup.yaml
│   └── cover-letter-variants/
│       ├── master.yaml        ← static cover-letter variants
│       ├── ai_platform.yaml
│       ├── infra.yaml
│       └── startup.yaml
├── docs/resume-research/      ← trusted evidence corpus (you write these)
├── jobs/
│   ├── inputs/                ← raw JDs you save off
│   └── generated/             ← per-JD outputs from the agent
└── output/                    ← rendered static-variant PDFs
```

## `data/master.yaml`

Your one source of truth. Variants filter or override this content; cover
letters pull contact info from `profile`. Schema:
[src/tailord/schemas/master.schema.yaml](../src/tailord/schemas/master.schema.yaml).

Required: `profile.name`, `profile.email`, at least one `experience` entry.

Every experience/project/education entry needs a stable `id`. Bullets need
a stable `id` and `text`. Variants reference those ids.

```yaml
profile:
  name: Jane Doe
  email: jane@example.com
  headline: Senior Software Engineer
  location: Brooklyn, NY
  links:
    - { label: LinkedIn, url: https://linkedin.com/in/jane-doe, display: linkedin.com/in/jane-doe }

experience:
  - id: acme_labs
    company: Acme Labs
    role: Senior Software Engineer
    start: March 2022
    end: Present
    bullets:
      - id: acme_workflow_engine
        priority: 100
        impact: high
        tags: [platform, backend, distributed]
        text: >-
          Designed and led a **distributed workflow engine** ...
```

`**bold**` is the only Markdown the renderer respects.

## `data/user-preferences.yaml`

User-specific constraints that the skills read at runtime. Replaces the
bits that used to be hard-coded in `SKILL.md` files.
Schema: [src/tailord/schemas/user-preferences.schema.yaml](../src/tailord/schemas/user-preferences.schema.yaml).

Top-level fields:

| Field | Used by | Effect |
| --- | --- | --- |
| `work_authorization.requires_sponsorship` | resume-job-fit-evaluator, resume-tailoring | If true, JDs that explicitly forbid sponsorship are gated to "No-go". |
| `work_authorization.type` | (informational) | E.g. "H1B", "OPT", "US citizen". |
| `targets.roles` | resume-job-fit-evaluator | Role families the candidate is targeting. |
| `targets.anti_roles` | resume-job-fit-evaluator | Role families the candidate explicitly does not want — applied as a compatibility cap. |
| `targets.geo` | (informational) | Acceptable locations / remote modes. |
| `targets.seniority` | (informational) | Acceptable levels. |
| `evidence_corpus_dir` | resume-tailoring, cover-letter-writing | Path to evidence docs (default: `docs/resume-research`). |
| `cover_letter.voice.description` | cover-letter-writing | Voice guide passed to the agent. |
| `cover_letter.voice.forbidden_phrases` | cover-letter-writing | Banned phrases (e.g. "I am writing to apply"). |
| `cover_letter.salutation_default` | renderer | "Dear Hiring Team" by default. |
| `cover_letter.signoff` | renderer | "Best," by default. |
| `cover_letter.length.{min_words, max_words}` | renderer | Warn-to-stderr if the body is outside bounds. |

## `data/variants/<name>.yaml`

Static resume variants. Tag-based filters over `master.yaml`. Schema:
[src/tailord/schemas/variant.schema.yaml](../src/tailord/schemas/variant.schema.yaml).

Skeleton:

```yaml
name: ai_platform
display_name: Platform Engineer
output_filename: jane_doe_ai_platform
page_format: Letter
mode: normal

include_tags: [platform, distributed, backend]
exclude_tags: [mobile]
max_bullets_per_role: 4
max_bullets_per_project: 3

section_order: [profile, experience, projects, skills, education]
```

Filtering:

1. Drop bullets whose tags intersect `exclude_tags`.
2. Keep bullets sharing a tag with `include_tags` (empty = keep all).
3. Sort survivors by `priority` desc, truncate to caps.
4. Bullets with `pinned: true` skip filters and caps.
5. A role/project that ends up with fewer than `min_bullets_per_role`
   (default 2) survivors is dropped entirely — a 1-bullet stub reads
   worse than an omission.

## `data/variants/<job-slug>.yaml` (job-specific variants)

Written by the `resume-tailoring` skill under
`jobs/generated/<slug>/variant.yaml`. Adds explicit-selection mechanics
on top of tag filtering:

```yaml
bullet_select:                # exact bullet ids, in order
  acme_labs:
    - acme_workflow_engine
    - acme_event_bus
    - derived_workflow_dag    # ← defined in extra_bullets below

bullet_overrides:             # rewrite a canonical bullet's text
  acme_event_bus: >-
    Operate a **Kafka-backed event bus** at 5K events/sec ...

extra_bullets:                # inject net-new bullets, cite evidence
  acme_labs:
    - id: derived_workflow_dag
      priority: 96
      tags: [platform, distributed]
      source:
        file: docs/resume-research/workflow-engine.md
        heading: Token-Based Execution Engine
      text: >-
        Designed Acme's **token-based DAG executor** ...

skills_override:              # full replacement for skills section
  - category: Languages
    items: [Python, TypeScript, Go, SQL]
```

When `bullet_select` is provided for a role, tag filters + caps are
skipped for that role. The agent has decided.

## `data/cover-letter-variants/<name>.yaml`

Per-variant cover letter content. Schema:
[src/tailord/schemas/cover-letter-variant.schema.yaml](../src/tailord/schemas/cover-letter-variant.schema.yaml).

```yaml
name: master
display_name: Cover Letter — Default
output_filename: jane_doe_cover_letter_master
page_format: Letter

recipient:
  team: Hiring Team
  company: ""
  role: ""

sections:
  opening_hook: |
    <1-2 sentences>
  why_them: |
    <1-2 sentences>
  why_me: |
    <2-3 sentences, grounded in master.yaml or evidence corpus>
  closing: |
    <1 sentence>
```

The renderer pulls contact info from `master.yaml`'s `profile` and voice
constraints from `user-preferences.cover_letter` — never duplicate them
here.

## `docs/resume-research/*.md`

Your trusted evidence corpus. The `resume-tailoring` and
`cover-letter-writing` skills draw from these to justify bullet rewrites
and `extra_bullets` entries. See
[src/tailord/skills/resume-evidence-review/SKILL.md](../src/tailord/skills/resume-evidence-review/SKILL.md)
for the trust rules.

There is no required structure — write whatever helps a future reader
verify a claim. A common layout: one doc per project, with section
headings the agent can cite via the `source.heading` field.

## `jobs/inputs/` and `jobs/generated/`

`inputs/`: where you save off raw JDs (Markdown or plain text).
`generated/`: per-JD outputs. The agent populates this dir with:

```
jobs/generated/<slug>/
├── notes.md            # agent's analysis, kept/dropped/rewrote, risks
├── variant.yaml        # the tailored job-specific variant
├── resume.pdf          # rendered output
├── cover-letter.yaml   # tailored cover letter
└── cover-letter.pdf    # rendered output
```

Both are typically gitignored in real vaults — they're build artifacts.

## `output/`

Rendered PDFs for static variants land here. Typically gitignored.
