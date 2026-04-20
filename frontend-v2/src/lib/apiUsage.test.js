import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { formatApiUsage } from './apiUsage.js';

// Shape mirrors UsageAggregator.summary() in backend/core/usage.py.
const samplePresent = {
  calls: [
    {
      label: 'synthesis',
      model: 'claude-sonnet-4-6',
      input_tokens: 120,
      cache_creation_input_tokens: 800,
      cache_read_input_tokens: 2400,
      output_tokens: 540,
      cost_usd: 0.013456,
    },
  ],
  totals: {
    input_tokens: 120,
    cache_creation_input_tokens: 800,
    cache_read_input_tokens: 2400,
    output_tokens: 540,
  },
  total_cost_usd: 0.013456,
};

describe('formatApiUsage — renders when present', () => {
  it('formats totals and cost into display strings', () => {
    const out = formatApiUsage(samplePresent);
    assert.ok(out, 'expected a non-null result when api_usage is present');
    // 120 + 800 + 2400 = 3320 input tokens processed
    assert.equal(out.inputTokens, '3,320');
    assert.equal(out.outputTokens, '540');
    assert.equal(out.costUsd, '$0.0135');
  });
});

describe('formatApiUsage — renders nothing when absent', () => {
  it('returns null for undefined', () => {
    assert.equal(formatApiUsage(undefined), null);
  });

  it('returns null for null (pre-Brief-10 archived answers)', () => {
    assert.equal(formatApiUsage(null), null);
  });

  it('returns null when calls array is missing', () => {
    assert.equal(formatApiUsage({ totals: {}, total_cost_usd: 0 }), null);
  });

  it('returns null when calls array is empty', () => {
    assert.equal(
      formatApiUsage({ calls: [], totals: {}, total_cost_usd: 0 }),
      null,
    );
  });
});
