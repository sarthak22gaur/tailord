"""Append-only local event logging for runner calls."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tailord.config import Config
from tailord.pricing import compute_cost_usd
from tailord.runners import RunResult


def events_path(vault: Path | None = None) -> Path:
    root = vault or Config.load().vault
    return root / ".tailord" / "events.jsonl"


def log_runner_call(kind: str, run_result: RunResult, wall_time_ms: int) -> Path:
    usage = run_result.usage
    if run_result.cost_usd is not None:
        cost_usd = run_result.cost_usd
    elif usage is not None:
        cost_usd = compute_cost_usd(run_result.model, usage)
    else:
        cost_usd = 0.0
    row = {
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "kind": kind,
        "model": run_result.model,
        "input_tokens": usage.input_tokens if usage else 0,
        "output_tokens": usage.output_tokens if usage else 0,
        "cache_creation_tokens": usage.cache_creation_tokens if usage else 0,
        "cache_read_tokens": usage.cache_read_tokens if usage else 0,
        "cost_usd": cost_usd,
        "wall_time_ms": int(wall_time_ms),
    }
    path = events_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return path
