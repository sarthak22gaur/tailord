# Browser extension + jd-bridge

The recommended job-page workflow. Turns "I see a LinkedIn job" into a fit
evaluation first, then lets you explicitly generate a tailored resume or
resume + cover letter. The extension is only the front door; the local
`jd-bridge` remains the engine.

## Architecture

```
┌────────────────┐ POST /jobs   ┌────────────────────┐ spawn  ┌────────────┐
│  browser ext   │ ───────────► │  jd-bridge (Node)  │ ─────► │   claude   │
│  (Chrome/FF)   │   localhost  │  Fastify + SQLite  │  -p    │    -p      │
│                │              │  bound to 127.0    │        │   skills/  │
│                │ ◄─ /jobs ─── │  worker pool       │ ◄──    │            │
│                │  GET notifs  │                    │        └────────────┘
│                │              │  serves PDFs       │
│                │ ◄─ /pdf/:id ─│                    │
└────────────────┘              └────────────────────┘
        │                                │
        │                                │
        ▼                                ▼
  popup UI                          evaluation result
  list of jobs                      tailored PDFs on request
  generate / skip / apply           in $VAULT/jobs/generated/<slug>/
```

## Prerequisites

- Python 3.11+ with `tailord` installed, for example with `pipx install
  'tailord[pdf] @ git+https://github.com/sarthak22gaur/tailord.git'`.
- [Claude Code](https://docs.claude.com/en/docs/claude-code) (the `claude` CLI)
  on PATH — the bridge invokes `claude -p` to evaluate and generate.
- Node.js 20.6+ with `npm` on PATH. The bridge start command uses
  `node --env-file`, which older Node versions do not support.
- Chrome/Edge with the Tailord extension installed. Firefox/Zen and developer
  sideloading use generated packages from this repo.
- The `claude` Code CLI installed and authenticated on $PATH. The bridge
  worker only supports the `claude_cli` runner today.
- A vault you can render against (`tailord validate` passes).
- A working `tailord build` — the bridge calls the same skills, so
  if the renderer works, the bridge will too.

The skills the bridge invokes (`resume-job-fit-evaluator`,
`resume-tailoring`, `cover-letter-writing`) live at `.claude/skills/` in the
framework directory used as the Claude CLI working directory. Editable clones
use the committed `.claude/skills/` tree. Packaged installs create a small
runtime workspace under `$XDG_DATA_HOME/tailord/framework` (or
`~/.local/share/tailord/framework`) with those skills and a minimal Makefile.

## Setup

### 1. Install the extension

For Chrome/Edge, install the unlisted Tailord extension from the Chrome Web
Store once that listing is available. The extension talks only to
`http://127.0.0.1` or `http://localhost`; there is no hosted Tailord backend.

For local testing or Firefox/Zen, build the browser-specific packages from a
clone:

```bash
node tools/jd-extension/scripts/package-extension.mjs
```

This writes:

```text
dist/jd-extension/chrome/
dist/jd-extension/firefox/
dist/jd-extension/tailord-extension-chrome-0.1.0.zip
dist/jd-extension/tailord-extension-firefox-0.1.0.zip
```

The generated Chrome package uses Manifest V3 `background.service_worker` only.
The generated Firefox package uses the Firefox background script shape and
includes `browser_specific_settings`.

### 2. Set up the local bridge

The bridge is not shipped inside the browser extension. It is shipped with the
Tailord Python package and installed into a user-writable runtime directory by
`setup-bridge`:

```bash
pipx install 'tailord[pdf] @ git+https://github.com/sarthak22gaur/tailord.git'
tailord install-browsers
tailord init ~/resume-vault          # if you haven't already
tailord --vault ~/resume-vault setup-bridge
```

`setup-bridge` first copies the packaged bridge into
`$XDG_DATA_HOME/tailord/jd-bridge` (default:
`~/.local/share/tailord/jd-bridge`) unless you are running from an editable
clone, where it uses `tools/jd-bridge/`. It then checks Node.js and `npm`,
writes `.env` with a random `BRIDGE_TOKEN` and resolved `RESUME_VAULT` +
`RESUME_FRAMEWORK` paths, and runs `npm install`.

The runtime bridge and framework workspace are refreshed by `setup-bridge` and
`serve`. Treat them as generated output; use an editable clone if you want to
modify bridge code or Tailord skills.

Then start the bridge:

```bash
tailord --vault ~/resume-vault serve
```

The bridge logs the resolved vault + framework + config source on
startup. If the vault doesn't have `data/master.yaml`, or the framework
doesn't have `.claude/skills/`, it refuses to start with a clear error.

### 3. Pair the extension

Open the extension's options page (right-click the toolbar icon → Options)
and paste:

- **Bridge URL**: `http://127.0.0.1:8787` (or your `BRIDGE_PORT`).
- **Bridge token**: the same `BRIDGE_TOKEN` from the `.env` path printed by
  `tailord setup-bridge`.

Hit "Test connection" — it should report concurrency / running / pending.
If it says the token was rejected, copy the `BRIDGE_TOKEN=` value from
the bridge `.env` again and save Options before retesting.

### Doing bridge setup manually

Editable clones can still run the bridge from `tools/jd-bridge/` by hand:

```bash
cd tools/jd-bridge
cp .env.example .env
# Edit .env:
#   BRIDGE_TOKEN=<openssl rand -hex 24>
#   RESUME_VAULT=/path/to/your/vault
#   RESUME_FRAMEWORK=/path/to/the/cloned/tailord  # repo root with .claude/skills
npm install
node --env-file=.env src/server.js
```

Then load a generated extension package if you are not using the Chrome Web
Store build:

- **Chrome/Edge**: `chrome://extensions` → enable Developer mode → "Load
  unpacked" → select `dist/jd-extension/chrome/`.
- **Firefox/Zen**: `about:debugging#/runtime/this-firefox` → "Load
  Temporary Add-on" → pick `dist/jd-extension/firefox/manifest.json`.

## Usage

1. Open a LinkedIn job page (`https://www.linkedin.com/jobs/view/...` or
   the new AI-job-search surface).
2. Click the extension icon. The popup shows queued + recent jobs.
3. Click "Queue this job". The extension extracts the JD from the page
   and POSTs it to the bridge.
4. The bridge picks it up, runs the evaluator, and updates the popup with
   compatibility / consideration scores, grade, recommendation, blockers,
   and work-authorization notes.
5. Choose "Generate resume", "Resume + cover", or "Skip". Cover letters are
   opt-in and are not generated unless you ask.
6. You get a desktop notification when artifact generation is `done`. Click
   the notification to open the resume PDF, or use "Resume" / "Cover" in the
   popup.
7. Click "Mark applied" once you've actually applied — it greys out the
   row so you don't double-apply.

The generated files are also on disk under
`<vault>/jobs/generated/<job-slug>/`: `resume.pdf`, `variant.yaml`, and
`notes.md`; `cover-letter.pdf` appears only when you choose resume + cover.
The popup's "Resume" and "Cover" buttons open those PDFs through the local
bridge.

## Configuration knobs

In the bridge `.env` printed by `tailord setup-bridge`:

| Key | Default | What it does |
| --- | --- | --- |
| `BRIDGE_PORT` | `8787` | HTTP port the bridge binds on 127.0.0.1. |
| `BRIDGE_TOKEN` | (required) | Shared secret the extension sends in `X-Bridge-Token`. |
| `BRIDGE_ALLOW_NO_TOKEN` | `0` | Set to `1` only for local unauthenticated dev. |
| `BRIDGE_ALLOWED_ORIGINS` | (empty) | Extra CORS origins. Extension origins are auto-allowed. |
| `CONCURRENCY` | `4` | How many JDs to process in parallel. |
| `CLAUDE_TIMEOUT_MS` | `1800000` (30 min) | Per-job timeout. |
| `CLAUDE_OUTPUT_LIMIT_BYTES` | `2097152` (2 MiB) | Cap on stdout per claude invocation. |
| `RESUME_VAULT` | (config-discovery) | Vault root. Overrides `.resumerc.yaml`. |
| `RESUME_FRAMEWORK` | runtime workspace | Directory where Claude discovers `.claude/skills/`. |
| `CLAUDE_BIN` | `claude` | Path to the Claude Code CLI. |
| `CLAUDE_FLAGS` | `--dangerously-skip-permissions --output-format=json` | Flags passed to every `claude -p`. |

Bridge state (SQLite job history) is stored at `<vault>/.tailord/jobs.db` —
no knob. Putting state outside the vault was a bug; the path is now derived
from `RESUME_VAULT` so job history follows the user's data.

## Packaging and Chrome Web Store checklist

```bash
node tools/jd-extension/scripts/make-icons.mjs
node tools/jd-extension/scripts/package-extension.mjs
node --test tools/jd-extension/test/package-extension.test.mjs
```

Before submitting the Chrome zip:

1. Upload `dist/jd-extension/tailord-extension-chrome-0.1.0.zip`.
2. Load `dist/jd-extension/chrome/` with "Load unpacked" and confirm Chrome
   reports no manifest warning about `background.scripts`.
3. Start the bridge, save the bridge token in Settings, and verify "Test
   connection" succeeds.
4. Queue a LinkedIn job, wait for evaluation, generate a resume, and open the
   PDF.
5. Use the copy, permission justifications, reviewer notes, privacy URL, and
   screenshot from [../chrome-web-store.md](../chrome-web-store.md).
6. Submit the first listing as **unlisted**.

Listing/privacy copy should state that the extension sends JD text only to the
user's local Tailord bridge at `127.0.0.1` / `localhost`; Tailord does not run a
hosted backend.

## Troubleshooting

**Popup says "bridge unreachable"** — the bridge is not running, the port
is wrong in Options, or the token is rejected. Start it with:

```bash
tailord serve
```

Then open Options and hit "Test connection". If Options says the token was
rejected, copy the `BRIDGE_TOKEN=` value from `.env` again.

**`setup-bridge` says "node not found", "npm not found", or Node is too old** —
install Node.js 20.6+ with npm, then re-run `tailord setup-bridge`. The command
does not write `.env` until these prerequisites pass.

**Bridge refuses to start with "vault is missing data/master.yaml"** —
your `RESUME_VAULT` (or discovered config file) doesn't point at a valid
vault. Verify with `tailord doctor` from the CLI.

**Jobs queue but never complete** — claude is probably hung. Check the
bridge stdout. Default timeout is 30 minutes; lower `CLAUDE_TIMEOUT_MS`
during debugging.

**Job fails with "RESULT line is incomplete"** — the agent didn't emit a
final `RESULT:` line. Look at the bridge logs; usually the prompt or a
skill was edited in a way that confuses the agent.

**LinkedIn extraction returns 0 chars** — first open the job detail pane or
`/jobs/view/...` page, wait for the description to load, then retry. If it
still fails, the popup includes a `Debug:` block with the selectors and
text blocks the adapter tried; paste that diagnostic into an issue. While
the adapter is fixed, copy-paste the JD into `tailord score-job`.

## Extending to other job sites

`tools/jd-extension/content/adapters/` is a registry. Add a new file like
`adapters/<site>.js` that calls `__jdRegister({ name, hosts, extract })`
where `extract()` returns `{ jd, url, company, title }` — same shape as
the LinkedIn adapter. Then add the site to `host_permissions` and a
matching `content_scripts` entry in `manifest.json`.

The bridge doesn't care which site the JD came from; the adapter just
needs to hand it well-formed `{jd, company, title, url}`.
