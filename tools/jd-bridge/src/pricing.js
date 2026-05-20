// Token pricing helpers for local bridge usage accounting.
// Keep in sync with src/tailord/pricing.py. Verified against
// https://platform.claude.com/docs/en/about-claude/pricing on 2026-05-20.
// Uses first-party/global Claude API rates, not US-only inference, batch,
// fast-mode, or 1-hour cache-write multipliers.

export const PRICING_PER_MTOKEN = {
  'claude-haiku-4-5': { in: 1.00, out: 5.00, cache_w: 1.25, cache_r: 0.10 },
  'claude-sonnet-4-6': { in: 3.00, out: 15.00, cache_w: 3.75, cache_r: 0.30 },
  'claude-opus-4-7': { in: 5.00, out: 25.00, cache_w: 6.25, cache_r: 0.50 },
};

function pricingForModel(model) {
  if (!model) return null;
  const modelId = String(model).toLowerCase();
  for (const [prefix, pricing] of Object.entries(PRICING_PER_MTOKEN)) {
    if (modelId.startsWith(prefix)) return pricing;
  }
  return null;
}

function intValue(value) {
  return Number.isInteger(value) ? value : 0;
}

export function normalizeUsage(usage) {
  if (!usage || typeof usage !== 'object') return null;
  return {
    input_tokens: intValue(usage.input_tokens),
    output_tokens: intValue(usage.output_tokens),
    cache_creation_tokens: intValue(usage.cache_creation_input_tokens ?? usage.cache_creation_tokens),
    cache_read_tokens: intValue(usage.cache_read_input_tokens ?? usage.cache_read_tokens),
  };
}

export function computeCostUsd(model, usage) {
  const pricing = pricingForModel(model);
  if (!pricing) {
    console.warn(`warning: unknown Claude model for pricing: ${JSON.stringify(model)}`);
    return 0.0;
  }
  return (
    usage.input_tokens * pricing.in
    + usage.output_tokens * pricing.out
    + usage.cache_creation_tokens * pricing.cache_w
    + usage.cache_read_tokens * pricing.cache_r
  ) / 1_000_000;
}
