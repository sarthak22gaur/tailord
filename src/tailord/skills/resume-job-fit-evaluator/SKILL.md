---
name: resume-job-fit-evaluator
description: Critically evaluate job descriptions against the candidate's resume, evidence corpus, positioning, work-authorization constraints, and hiring-screen likelihood. Use when the user asks whether to apply, asks for job fit, compatibility, ranking, scoring, chances of being considered, or wants a JD triaged before tailoring the resume.
---

# Resume job fit evaluator

Use this skill before deep tailoring when the user wants to know whether a job
is worth applying to. Be candid. The goal is to protect the candidate's time
and avoid overfitting the resume to roles that are structurally weak matches.

## Inputs

- A job description pasted in chat, linked by URL, or saved under
  `jobs/inputs/`.
- Optional company context, recruiter notes, referral context, location
  preferences, or compensation constraints.

If the user gives a URL or asks for the latest live posting, fetch the current
posting before scoring. If you cannot access it, say so and score only the
provided text.

## Vault evidence to read

Always read first:

- `data/user-preferences.yaml` — work-authorization gate, target/anti-target
  role families, geo, seniority. Treat these as hard constraints. If the file
  is missing or a key is unset, fall back to neutral (no gating on that key).
- `data/master.yaml` — canonical resume facts, bullets, skills, dates, and
  education.

Read selectively:

- `${user-preferences.evidence_corpus_dir}/12-positioning-and-narrative.md` if
  present — current target positioning and strong-fit / weak-fit map. Read
  whenever it exists.
- `skills/resume-evidence-review/SKILL.md` — trust rules for claims.
- Specific files under the evidence corpus dir only if the JD hinges on a
  topic not obvious from `data/master.yaml`.

Do not invent experience from the JD. A JD requirement can only be marked as
matched if it is present in `data/master.yaml` or supported by an evidence
doc.

## First-pass gates

Run these before assigning a normal score.

### Work authorization

Read `data/user-preferences.yaml`. If `work_authorization.requires_sponsorship`
is `true`, scan the JD for sponsorship language:

- **Explicit sponsorship yes**: proceed and mark as a positive signal.
- **Silent or ambiguous**: proceed, but record sponsorship as an open risk.
- **Explicit sponsorship no**: score the role as `No-go`. Quote the line.
  Cap consideration score at 10. Examples of explicit no: "no sponsorship",
  "must be authorized without sponsorship now or in the future", "US citizens
  only", "permanent residents only", ITAR-only work, active-clearance-only
  roles when citizenship is a hard requirement.

If `requires_sponsorship` is `false` or missing, skip this gate.

### Role-family gate

Compare the JD's core work to `user-preferences.targets`:

- If the JD lands clearly inside `targets.roles`, treat as strong-fit.
- If the JD lands clearly inside `targets.anti_roles`, say so directly. Do
  not rescue the score with incidental keyword overlap.
- If the JD straddles both, lean on the resume evidence to break the tie.

If `targets` is empty or missing, skip this gate and rely on the rubric
alone.

## Scores

Return two 0-100 scores:

- **Compatibility score**: how well the actual work matches the candidate's
  evidenced experience and desired positioning.
- **Consideration score**: how likely a recruiter or hiring manager is to
  advance them based on the posting's screeners, market signals, and
  constraints.

The consideration score is not a statistical probability. It is a recruiting
screen estimate based only on the JD and the resume evidence available.

### Weighted rubric

Score each category, then add the points.

| Category | Points | What to evaluate |
| --- | ---: | --- |
| Role trajectory fit | 25 | Whether the core work aligns with the candidate's positioning (see `user-preferences.targets`). |
| Hard requirement match | 25 | Must-have languages, systems, years, degree, domain, and production scope. |
| Differentiator strength | 15 | Which evidenced strengths from `master.yaml` / the evidence corpus would stand out. |
| Seniority calibration | 15 | Whether title/level expectations match the resume's scope without overclaiming. |
| Resume / ATS surface match | 10 | Supported keyword overlap visible in `data/master.yaml` or safe variants. |
| Friction and risk | 10 | Sponsorship, citizenship, clearance, location, domain mismatch, or missing must-haves. |

For each category, explain the score in one short sentence.

### Caps and penalties

Apply caps after scoring:

- Explicit sponsorship no (when sponsorship is required), US-citizen-only,
  permanent-resident-only, or active-clearance-only: consideration cap 10.
- Core role lands inside `user-preferences.targets.anti_roles`: compatibility
  cap 55 unless the JD has a substantial overlap with `targets.roles`.
- Missing a true hard requirement that appears mandatory and non-transferable:
  consideration cap 45.
- "Nice to have" gaps should reduce the score, not cap it.
- JD asks for tools that are absent from evidence: mark as unsupported. Do not
  treat adjacent experience as an exact match.
- A referral, direct recruiter outreach, or hiring-manager warm intro may
  raise consideration by up to 10 points, but it does not change
  compatibility.

## Bands

Use both a letter grade and action recommendation:

| Grade | Score | Recommendation |
| --- | ---: | --- |
| A | 85-100 | Apply aggressively; tailor deeply. |
| B | 70-84 | Good target; tailor with a sharp angle. |
| C | 55-69 | Possible but selective; apply if company/role is strategically interesting. |
| D | 35-54 | Low ROI; only apply with referral or unusual interest. |
| F | 0-34 | No-go or very weak match. |

If compatibility and consideration land in different bands, use the lower
band as the final apply priority.

## Requirement matrix

Build a compact table with these columns:

| JD requirement | Importance | Evidence | Match |
| --- | --- | --- | --- |

Use these match labels:

- **Strong** — directly supported by canonical resume or evidence corpus.
- **Partial** — adjacent or transferable, but not an exact match.
- **Weak** — thin evidence or only older / secondary experience.
- **Missing** — no evidence. Do not spin it.
- **Blocker** — likely to stop the application regardless of technical fit.

Evidence should cite `data/master.yaml` bullet ids, skill categories,
education entries, or evidence-doc headings. If you did not verify a claim,
label it unverified.

## Output format

Use this structure:

```markdown
# Job Fit: <Company> - <Role>

**Verdict:** <A-F> / <Apply aggressively | Good target | Selective | Low ROI | No-go>
**Compatibility:** <score>/100
**Consideration:** <score>/100
**Work authorization:** <yes | no | not mentioned | ambiguous | n/a> — <short note>

## Why
2-4 sentences, direct and critical.

## Score Breakdown
| Category | Score | Rationale |
| --- | ---: | --- |

## Requirement Matrix
| JD requirement | Importance | Evidence | Match |
| --- | --- | --- | --- |

## Strong Signals
- ...

## Risks / Gaps
- ...

## Application Angle
1-3 bullets on the best honest positioning if the candidate chooses to apply.

## Recommendation
One clear next step: tailor now, apply only with referral, ask recruiter about
sponsorship, save for later, or skip.
```

For multiple JDs, score each using the same rubric, then rank by final apply
priority. Put the ranking first, then individual scorecards.

## Hard rules

- Do not write or modify a tailored `variant.yaml` unless the user explicitly
  asks to tailor after the evaluation.
- Do not overstate chances. "Possible with referral" is better than false
  confidence.
- Do not add positioning the candidate hasn't earned. Use the positioning
  doc (if present) as the guardrail.
- Do not treat a JD's language as proof that the candidate has done that
  work.
- Surface missing evidence and screen-out constraints early, even when the
  company is attractive.
