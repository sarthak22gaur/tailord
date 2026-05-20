# Privacy & data flow

`tailord` runs on your machine. The only network call the framework
ever makes is the LLM API call, and only when you ask for one.

## What stays local

Everything in your vault is read from / written to disk:

- `data/master.yaml`, `data/user-preferences.yaml`, variants, cover-letter
  variants, evidence corpus.
- All generated PDFs (resume + cover letters).
- The SQLite job database used by the bridge (`<vault>/.tailord/jobs.db`).
- All bridge logs.

There is no telemetry. The framework does not check for updates, register
analytics, or call home.

Tailord does not sell job descriptions, browsing activity, or resume data, and
does not use them for advertising.

## What goes over the network

| When | Where it goes | What's sent |
| --- | --- | --- |
| `tailord score-job` (default `claude_cli`) | Wherever your local `claude` CLI is configured to send (typically api.anthropic.com via the Claude Code SDK). | The skill text, your `master.yaml`, your `user-preferences.yaml`, and the JD; mediated by the CLI. |
| `tailord score-job ... --runner anthropic_api` _(untested path)_ | api.anthropic.com | Same as above, sent directly via the Anthropic SDK. |
| Bridge processes a queued JD (via the extension) | Wherever `claude` is configured. | The prompt template (`tools/jd-bridge/config/prompt.yaml`) + the JD. The skill files reference your vault paths, so the agent will then read `master.yaml`, `user-preferences.yaml`, and the evidence corpus locally. |
| `tailord install-browsers` | chromium download CDN | Chromium binary. One-time install. |
| `pipx install 'tailord[...] @ git+https://github.com/...'` | github.com + package indexes for dependencies | The framework itself and Python dependencies. |

The vault is **never** uploaded as a single payload. The agent reads
individual files (via local filesystem tool use) only when its
reasoning needs them.

## What the browser extension sees

The extension runs only on `https://www.linkedin.com/jobs/*` (declared in
`manifest.json` host permissions). On a job page:

1. The content script reads the visible DOM — the same text you would see
   if you copy-pasted the page.
2. It POSTs the JD text + URL + company + title to `http://127.0.0.1:8787`
   (your local bridge), authenticated by the token created by
   `tailord setup-bridge`.
3. The bridge stores the JD in its local SQLite DB and triggers `claude`.

The extension does **not** auto-collect anything in the background. Nothing
happens until you click "Queue this job" in the popup.

## What the bridge sees

The bridge is a Node Fastify server bound to `127.0.0.1`. Packaged installs run
it from `~/.local/share/tailord/jd-bridge`; editable clones can run it from
`tools/jd-bridge/`. It does not accept external connections. Routes:

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /health` | open | Liveness + queue depth |
| `GET /pdf/:id`, `GET /cover-letter/:id` | open | Stream rendered PDFs (locked to vault output/ + jobs/generated/) |
| `GET /jobs`, `GET /jobs/:id` | token | List + fetch job state |
| `POST /jobs` | token | Queue a JD |
| `POST /jobs/:id/applied` | token | Toggle the "I applied" marker |
| `GET /events` | token | SSE stream of state transitions |

The token is a SHA-256 + `timingSafeEqual` compare against a shared secret
the user generates and pastes into the extension's options page. The PDF
routes are open because browsers can't attach custom headers when opening
URLs in a new tab — being bound to 127.0.0.1 is the access boundary.

The PDF allowlist (in `pdf-paths.js`) refuses anything outside the
vault's `output/` and `jobs/generated/` directories, refuses symlinks,
and re-resolves real paths after lstat so a symlink raced in between
checks is also rejected.

## What ends up in logs

Fastify's default logger logs request/response lines but **not** request
bodies. The JD text is therefore not in any log file at `INFO` level. The
queue and SSE event payloads carry only the parsed `RESULT` object from
the LLM (score, paths, etc.), not the JD itself.

If you set `LOG_LEVEL=trace`, Fastify may log more. Don't ship logs.

## LinkedIn's terms of service

The browser extension extracts the JD on the page you're already looking
at. It does **not** crawl, list, or paginate — it operates only when you
click. This is the same affordance as copy-paste. That said, automated
extraction of LinkedIn pages is in a gray area under LinkedIn's ToS; if
you're worried, paste JDs into `tailord score-job` manually.

## Summary

A reasonable threat model for using this framework:

- Your laptop is trusted.
- Your Anthropic API key is trusted (or your `claude` CLI install is).
- Anthropic's API is trusted to the extent you trust them with the prompts
  you send. The system prompt includes your `master.yaml` and
  `user-preferences.yaml`.
- The bridge is trusted to the extent your laptop is — it binds only to
  loopback and gates writes behind a per-install token.

If any of those assumptions don't hold (e.g. you're on a shared machine,
your API key is shared, you don't trust the LLM provider), don't run the
agent layer — the renderer pieces (`build`, `cover`, `validate`) are
entirely offline and remain useful on their own.
