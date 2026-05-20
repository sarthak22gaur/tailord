"""Pluggable model runners.

A runner takes a `system` prompt + `user` message and returns the final text
plus any token usage the backend exposes. Selection comes from
`tailord.config.Config.load().model_runner` (or a per-call override).
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Protocol


DEFAULT_MODEL = "claude-sonnet-4-6"


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass(frozen=True)
class RunResult:
    text: str
    usage: Usage | None
    model: str | None
    cost_usd: float | None = None


class ModelRunner(Protocol):
    name: str

    def run(self, *, system: str, user: str, max_tokens: int = 4096) -> RunResult:
        ...


def _int_attr(obj: object, name: str) -> int:
    if isinstance(obj, Mapping):
        raw = obj.get(name)
    else:
        raw = getattr(obj, name, None)
    return raw if isinstance(raw, int) else 0


def _usage_from_obj(obj: object | None) -> Usage | None:
    if obj is None:
        return None
    return Usage(
        input_tokens=_int_attr(obj, "input_tokens"),
        output_tokens=_int_attr(obj, "output_tokens"),
        cache_creation_tokens=_int_attr(obj, "cache_creation_input_tokens")
        or _int_attr(obj, "cache_creation_tokens"),
        cache_read_tokens=_int_attr(obj, "cache_read_input_tokens")
        or _int_attr(obj, "cache_read_tokens"),
    )


def _flags_with_json_output(flags: list[str]) -> list[str]:
    out: list[str] = []
    skip_next = False
    found = False
    for i, flag in enumerate(flags):
        if skip_next:
            skip_next = False
            continue
        if flag == "--output-format":
            out.append("--output-format=json")
            skip_next = i + 1 < len(flags)
            found = True
            continue
        if flag.startswith("--output-format="):
            out.append("--output-format=json")
            found = True
            continue
        out.append(flag)
    if not found:
        out.append("--output-format=json")
    return out


def _flags_with_model(flags: list[str], model: str | None) -> list[str]:
    """Force `--model=<model>` onto a claude CLI invocation. Strips any
    user-supplied --model so CLAUDE_MODEL is the single source of truth for
    both invocation and cost accounting."""
    if not model:
        return flags
    out: list[str] = []
    skip_next = False
    for i, flag in enumerate(flags):
        if skip_next:
            skip_next = False
            continue
        if flag == "--model":
            skip_next = i + 1 < len(flags)
            continue
        if flag.startswith("--model="):
            continue
        out.append(flag)
    out.append(f"--model={model}")
    return out


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _model_and_cost(payload: Mapping[str, object], aggregate: Usage | None) -> tuple[str, float | None]:
    from tailord.pricing import compute_cost_usd

    model_usage = payload.get("modelUsage")
    if isinstance(model_usage, Mapping) and model_usage:
        entries = [(m, u) for m, u in model_usage.items() if isinstance(u, Mapping)]
        if entries:
            dominant_model = entries[0][0]
            dominant_out = _int_attr(entries[0][1], "outputTokens")
            total = 0.0
            for m, u in entries:
                per_model = Usage(
                    input_tokens=_int_attr(u, "inputTokens"),
                    output_tokens=_int_attr(u, "outputTokens"),
                    cache_creation_tokens=_int_attr(u, "cacheCreationInputTokens"),
                    cache_read_tokens=_int_attr(u, "cacheReadInputTokens"),
                )
                total += compute_cost_usd(m, per_model)
                out = _int_attr(u, "outputTokens")
                if out > dominant_out:
                    dominant_model = m
                    dominant_out = out
            return dominant_model, total

    model = payload.get("model")
    if not isinstance(model, str):
        model = os.environ.get("CLAUDE_MODEL") or DEFAULT_MODEL
    cost = compute_cost_usd(model, aggregate) if aggregate is not None else None
    return model, cost


def _parse_claude_cli_output(stdout: str) -> RunResult:
    try:
        payload = json.loads(stdout.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"claude returned invalid JSON: {e}") from e

    text = payload.get("result")
    if not isinstance(text, str):
        message = payload.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        text = _content_text(content)
    if not isinstance(text, str):
        raise RuntimeError("claude JSON output did not include a result string")

    usage = _usage_from_obj(payload.get("usage"))
    model, cost_usd = _model_and_cost(payload, usage)
    return RunResult(text=text, usage=usage, model=model, cost_usd=cost_usd)


class ClaudeCliRunner:
    """Shells out to `claude -p`. Picks up whichever skills the user's
    Claude Code environment auto-discovers from `.claude/skills/`."""

    name = "claude_cli"

    def __init__(self, bin: str | None = None, extra_flags: list[str] | None = None):
        self.bin = bin or os.environ.get("CLAUDE_BIN") or "claude"
        flags_raw = os.environ.get("CLAUDE_FLAGS", "--dangerously-skip-permissions")
        self.extra_flags = extra_flags or [f for f in flags_raw.split() if f]

    def run(self, *, system: str, user: str, max_tokens: int = 4096) -> RunResult:
        prompt = f"{system}\n\n---\n\n{user}\n"
        flags = _flags_with_model(
            _flags_with_json_output(self.extra_flags),
            os.environ.get("CLAUDE_MODEL"),
        )
        result = subprocess.run(
            [self.bin, *flags, "-p"],
            input=prompt,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"claude exited with code {result.returncode}\n"
                f"--- stderr tail ---\n{result.stderr[-1000:]}"
            )
        return _parse_claude_cli_output(result.stdout)


class AnthropicApiRunner:
    """Anthropic SDK direct call. The system prompt is marked cacheable, so
    re-running the same skill across many JDs only pays for the system
    tokens once per 5-minute cache window."""

    name = "anthropic_api"

    def __init__(self, model: str | None = None):
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise SystemExit(
                "anthropic SDK is required for the anthropic_api runner. Install with:\n"
                "  pip install anthropic\n"
                f"(import error: {e})"
            )
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "ANTHROPIC_API_KEY env var is required for the anthropic_api runner."
            )
        self._Anthropic = Anthropic
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL

    def run(self, *, system: str, user: str, max_tokens: int = 4096) -> RunResult:
        client = self._Anthropic()
        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:  # noqa: BLE001
            if e.__class__.__module__.startswith("anthropic"):
                message = str(e)
                if (
                    e.__class__.__name__ == "AuthenticationError"
                    or "x-api-key" in message.lower()
                    or "authentication" in message.lower()
                ):
                    raise SystemExit(
                        "Anthropic rejected ANTHROPIC_API_KEY. Set a real key, "
                        "or use `--runner claude_cli` if you have the Claude CLI.\n"
                        f"(original error: {message})"
                    ) from e
                raise SystemExit(
                    "Anthropic API request failed. Check your network, model, "
                    f"and account access.\n(original error: {message})"
                ) from e
            raise
        from tailord.pricing import compute_cost_usd

        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        usage = _usage_from_obj(resp.usage)
        cost = compute_cost_usd(self.model, usage) if usage is not None else None
        return RunResult(text=text, usage=usage, model=self.model, cost_usd=cost)


def build_runner(name: str | None = None) -> ModelRunner:
    if not name:
        from tailord.config import Config
        name = Config.load().model_runner or "claude_cli"
    if name == "claude_cli":
        return ClaudeCliRunner()
    if name == "anthropic_api":
        return AnthropicApiRunner()
    raise SystemExit(f"unknown model_runner: {name!r} (expected claude_cli or anthropic_api)")
