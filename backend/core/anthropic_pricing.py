"""Anthropic model pricing (USD per 1M tokens) and cache multipliers.

Rates captured 2026-04 from the Anthropic public pricing page. Update
here when prices change — the aggregator / per-call cost calculation
reads only from this module, so instrumentation code is decoupled
from the rate sheet.

Cache multipliers follow Anthropic's billing model:
  • cache_creation_input_tokens — priced at 1.25× base input rate
    (write charge; 5-minute TTL by default)
  • cache_read_input_tokens     — priced at 0.1× base input rate
    (read charge; the cache-hit path)
  • input_tokens / output_tokens — base rates, unchanged

Unknown model IDs fall back to Sonnet rates. The fallback is deliberate
— missing from the table shouldn't zero-out cost reporting.
"""

from __future__ import annotations

from typing import Dict, TypedDict


class _ModelRate(TypedDict):
    input_per_mtok: float
    output_per_mtok: float


# Canonical pricing table. Keys are the model IDs the Anthropic SDK
# returns in `response.model` (which echoes the ID we requested).
PRICING: Dict[str, _ModelRate] = {
    # Sonnet family — all priced identically ($3 / $15 per MTok)
    "claude-sonnet-4-20250514": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "claude-sonnet-4-5": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "claude-sonnet-4-5-20250929": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "claude-sonnet-4-6": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    "claude-sonnet-4-7": {"input_per_mtok": 3.00, "output_per_mtok": 15.00},
    # Haiku family
    "claude-haiku-4-5": {"input_per_mtok": 0.80, "output_per_mtok": 4.00},
    "claude-haiku-4-5-20251001": {"input_per_mtok": 0.80, "output_per_mtok": 4.00},
    # Opus family — included for completeness
    "claude-opus-4-7": {"input_per_mtok": 15.00, "output_per_mtok": 75.00},
}

# Fallback for unknown model IDs. Sonnet is the safer over-estimate
# vs. Haiku (don't under-count spend) and the safer under-estimate
# vs. Opus (don't inflate).
_FALLBACK_RATE: _ModelRate = {"input_per_mtok": 3.00, "output_per_mtok": 15.00}

CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


def rate_for(model: str) -> _ModelRate:
    """Return the rate entry for `model`, falling back to Sonnet if unknown."""
    return PRICING.get(model, _FALLBACK_RATE)


def cost_usd(
    model: str,
    *,
    input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    output_tokens: int = 0,
) -> float:
    """Dollar cost of a single Anthropic call with cache accounting.

    Cache tokens are billed SEPARATELY from uncached input tokens —
    Anthropic reports them as disjoint counts, and we mirror that.
    Total input spend = base + write-premium + read-discount.
    """
    rate = rate_for(model)
    input_rate = rate["input_per_mtok"]
    output_rate = rate["output_per_mtok"]

    base_input_cost = input_tokens * input_rate
    cache_write_cost = cache_creation_input_tokens * input_rate * CACHE_WRITE_MULTIPLIER
    cache_read_cost = cache_read_input_tokens * input_rate * CACHE_READ_MULTIPLIER
    output_cost = output_tokens * output_rate

    return (base_input_cost + cache_write_cost + cache_read_cost + output_cost) / 1_000_000
