// Shape matches backend/core/usage.py UsageAggregator.summary():
//   { calls: [...], totals: { input_tokens, cache_creation_input_tokens,
//     cache_read_input_tokens, output_tokens }, total_cost_usd }
//
// Returns null when there's nothing worth showing (missing field, empty
// calls) so callers can render nothing rather than a broken layout.

const numberFmt = new Intl.NumberFormat('en-US');

export function formatApiUsage(apiUsage) {
  if (!apiUsage || !Array.isArray(apiUsage.calls) || apiUsage.calls.length === 0) {
    return null;
  }
  const totals = apiUsage.totals || {};
  const inputTokens =
    (totals.input_tokens || 0) +
    (totals.cache_creation_input_tokens || 0) +
    (totals.cache_read_input_tokens || 0);
  const outputTokens = totals.output_tokens || 0;
  const cost = Number(apiUsage.total_cost_usd || 0);

  return {
    inputTokens: numberFmt.format(inputTokens),
    outputTokens: numberFmt.format(outputTokens),
    costUsd: `$${cost.toFixed(4)}`,
  };
}
