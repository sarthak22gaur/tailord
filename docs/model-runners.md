# Model runners

`tailord` separates *what to ask the LLM* (the skills) from *how
the bytes get there* (the runner). Two runners ship; both implement the
same `ModelRunner` protocol in [`src/tailord/runners.py`](../src/tailord/runners.py).

| Runner | Triggered by | Requires |
| --- | --- | --- |
| `claude_cli` | default | `claude` CLI on $PATH, signed in. |
| `anthropic_api` (untested) | `--runner anthropic_api` or `model_runner: anthropic_api` in config | `ANTHROPIC_API_KEY` env var, `pip install '.[api]'`. |

> **`claude_cli` is the only path tailord has been used and tested with.** The
> `anthropic_api` runner is implemented but unexercised — treat it as
> experimental and expect rough edges.

Selection order:

1. `--runner` CLI flag (per-command override).
2. `model_runner:` field in `.resumerc.yaml`.
3. Default: `claude_cli`.

## When to use which

**`claude_cli`** — if you already use Claude Code interactively. The CLI
handles auth, skill discovery, tool use, and rate limiting. The bridge
uses this path today.

**`anthropic_api`** (untested) — in principle, for when you don't have the CLI
installed, or you want deterministic billing on your own API key, or you want
prompt caching to make repeated runs cheap. The system prompt is sent with
`cache_control: ephemeral`, so the second `score-job` against the same
skill (within a 5-minute window) only pays for the JD-side tokens.

## Prompt caching

The Anthropic API runner marks the system prompt as cacheable. The
system prompt for `score-job` is:

```
You are the resume-job-fit-evaluator skill.

<SKILL.md contents — ~200 lines, stable>

--- data/master.yaml ---
<your master.yaml — stable per session>

--- data/user-preferences.yaml ---
<your preferences — stable per session>
```

That entire block is ~3–10K tokens depending on your vault size. With
caching, the first call writes the cache and the next call (within 5
minutes) reads it for ~10% of the input price. If you're scoring a
batch of JDs, this matters.

## Adding a new runner

Implement the protocol:

```python
class MyRunner:
    name = "my_runner"

    def run(self, *, system: str, user: str, max_tokens: int = 4096) -> str:
        ...
```

Register it in `build_runner()` in `src/tailord/runners.py`. The CLI's
`--runner` choices list and the config schema currently hard-code the
two known names; if you add a runner you'd extend both.

Candidate future runners:

- A `bedrock` runner targeting AWS Bedrock for Anthropic models.
- An `ollama` runner targeting a local model for fully air-gapped use
  (the skills would need to be rewritten for a smaller-context model).
- A `vertex_ai` runner.

## Bridge vs CLI

The Python `score-job` (and future `tailor-job`) commands go through
`src/tailord/runners.py` and support both runners.

The Node bridge only supports `claude_cli` today. The full bridge
pipeline (score → tailor → render PDFs) needs agent-style tool use, and
the `anthropic_api` path would have to reimplement Read/Write/Bash tool
use in Node. That's a planned follow-up — see
`tools/jd-bridge/src/worker.js`. If you don't have the Claude CLI but
still want to score JDs, use `tailord score-job --runner anthropic_api`
directly from the CLI.
