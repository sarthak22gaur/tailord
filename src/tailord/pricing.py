"""Token pricing helpers for local usage accounting."""
from __future__ import annotations

import sys

from tailord.runners import Usage


# USD per million tokens. Keep in sync with tools/jd-bridge/src/pricing.js.
# Verified against https://platform.claude.com/docs/en/about-claude/pricing on
# 2026-05-20. This uses first-party/global Claude API rates, not US-only
# inference, batch, fast-mode, or 1-hour cache-write multipliers.
PRICING_PER_MTOKEN = {
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00, "cache_w": 1.25, "cache_r": 0.10},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00, "cache_w": 3.75, "cache_r": 0.30},
    "claude-opus-4-7": {"in": 5.00, "out": 25.00, "cache_w": 6.25, "cache_r": 0.50},
}


def _pricing_for_model(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    model_id = model.lower()
    for prefix, pricing in PRICING_PER_MTOKEN.items():
        if model_id.startswith(prefix):
            return pricing
    return None


def compute_cost_usd(model: str | None, usage: Usage) -> float:
    pricing = _pricing_for_model(model)
    if pricing is None:
        print(f"warning: unknown Claude model for pricing: {model!r}", file=sys.stderr)
        return 0.0

    return (
        usage.input_tokens * pricing["in"]
        + usage.output_tokens * pricing["out"]
        + usage.cache_creation_tokens * pricing["cache_w"]
        + usage.cache_read_tokens * pricing["cache_r"]
    ) / 1_000_000
