# Contributing to tailord

Thanks for considering a contribution. tailord is a solo-maintained project,
so a few words upfront about scope and process will save us both time.

## Before you open a PR

**Open an issue first** for anything beyond a typo, a doc fix, or a one-line
bug fix. A short issue ("here's the problem, here's my proposed shape, OK?")
takes 5 minutes and avoids the worst outcome — you spending a weekend on a
PR I have to decline.

**In scope:**

- Bug fixes (CLI, renderer, bridge, extension).
- New site adapters under `tools/jd-extension/content/adapters/` (Indeed,
  Lever, Greenhouse, etc.). The bridge doesn't care which site the JD came
  from; the adapter just needs to return `{ jd, url, company, title }`.
- New skill-aware clients in `tailord sync-skills` (add to the `CLIENTS`
  tuple in `src/tailord/sync_skills.py`).
- Doc improvements, especially troubleshooting entries from real failures
  you hit.
- `ModelRunner` implementations for other LLM providers.
- Test coverage for things that broke and shouldn't again.

**Out of scope:**

- Changes to the resume YAML schema. The framework/vault split locks the
  schema as v0.1's stable contract; breaking it strands existing users.
  Open an issue if you think a field is missing — that's a v0.2 discussion.
- "AI rewrites your bullets" features. tailord is evidence-only by design;
  see [POSITIONING.md](POSITIONING.md).
- Vault content (resumes, cover letters, sample data tailored to a
  specific person). The sample vault under
  `src/tailord/examples/sample-vault/` is the only candidate-shaped data
  that lives in this repo.
- Refactors that don't have a concrete bug or feature behind them. "Move X
  to Y for cleanliness" PRs will be declined; the codebase is small enough
  that abstraction overhead costs more than it saves.

## License

By contributing, you agree that your contributions are licensed under the
project's license: the [MIT License](LICENSE).

## Dev setup

```bash
git clone https://github.com/sarthak22gaur/tailord.git
cd tailord
pip install -e '.[pdf,api,dev]'
tailord install-browsers
tailord init ~/resume-vault-dev    # or point at the sample vault
```

For bridge work:

```bash
cd tools/jd-bridge
npm install
```

Node 20.6+ is required (the bridge uses `node --env-file`).

## Before you push

Run the same checks CI runs:

```bash
tailord validate                  # schema + structural checks against your vault
tailord sync-skills --check       # detects skill output-dir drift
ruff check src/tailord            # touched files at minimum
```

For bridge changes:

```bash
cd tools/jd-bridge
node --env-file=.env src/server.js  # boot the bridge, exercise the popup
```

For extension changes, sideload `tools/jd-extension/` in
`chrome://extensions` (Developer mode → Load unpacked) and verify the popup
+ queue flow still works on a real LinkedIn job page.

## PR shape

- One topic per PR. Small PRs ship; sprawling PRs sit.
- Title: imperative, present-tense ("add Indeed adapter", "fix popup
  refresh leak"). Doesn't need to be Conventional Commits.
- Body: what changed, why, and how you verified it. A 3-line description
  beats a 30-line one if both convey the same information.
- For skill changes: edit only `src/tailord/skills/<name>/SKILL.md`, then
  run `tailord sync-skills` and commit the regenerated `.claude/`,
  `.codex/`, `.opencode/` dirs together.
- For schema changes (rare): document the migration path in the same PR.

## What you can expect from me

- A first response within roughly a week, often faster. Solo project; no
  team to escalate to if I'm busy.
- An honest yes / no / needs-changes. I won't ghost a PR — if I have to
  decline, I'll say why.
- No bikeshedding. If the change is correct and matches the project's
  scope, style nits get a single comment, not a multi-round review.

## Security

Don't file security issues in the public tracker. Email
`sarthak22gaur@gmail.com` with the details. I'll acknowledge within a few
days, fix in private, and credit you in the release notes unless you'd
rather stay anonymous.

Things that are not security issues despite looking like them:

- The bridge binds to 127.0.0.1 and gates writes behind a per-install
  token. Loopback exposure is the access boundary.
- The PDF routes are intentionally unauthenticated — browsers can't attach
  headers when opening URLs in a new tab. They're locked to vault paths
  via the allowlist in `pdf-paths.js`.

If you find a way around either of those, that *is* a security issue and
I want to hear about it.
