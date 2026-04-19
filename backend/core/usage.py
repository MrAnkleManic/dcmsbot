"""Per-request LLM usage capture and aggregation.

The flow:
  1. Each call site in the request lifecycle (synthesis, rewriter, …)
     records an `LLMCall` against a shared `UsageAggregator`.
  2. The aggregator produces a summary dict that the `/query` handler
     returns as `api_usage` AND appends to the monthly JSON store.

`LLMCall.from_anthropic_usage` accepts the SDK's usage object as
duck-typed input — tests pass `SimpleNamespace`; production passes
`anthropic.types.Usage`. All fields default to zero so cache attrs
missing on older SDKs or non-cached calls don't blow up.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from backend.core.anthropic_pricing import cost_usd


@dataclass
class LLMCall:
    """One Anthropic API call's token counts + computed cost."""

    label: str
    model: str
    input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    output_tokens: int = 0

    @classmethod
    def from_anthropic_usage(cls, label: str, model: str, usage: Any) -> "LLMCall":
        """Build from any object with `input_tokens`/`output_tokens` attrs.

        Cache attributes are treated as optional (older SDKs, calls without
        cache_control). A `None` value on any attr is coerced to 0 because
        the SDK returns `None` for cache fields on non-cached responses.
        """
        def _get(attr: str) -> int:
            return int(getattr(usage, attr, 0) or 0)

        return cls(
            label=label,
            model=model,
            input_tokens=_get("input_tokens"),
            cache_creation_input_tokens=_get("cache_creation_input_tokens"),
            cache_read_input_tokens=_get("cache_read_input_tokens"),
            output_tokens=_get("output_tokens"),
        )

    def cost_usd(self) -> float:
        return cost_usd(
            self.model,
            input_tokens=self.input_tokens,
            cache_creation_input_tokens=self.cache_creation_input_tokens,
            cache_read_input_tokens=self.cache_read_input_tokens,
            output_tokens=self.output_tokens,
        )

    def to_record(self) -> dict:
        """Serialisable per-call record for the summary dict + JSON store."""
        return {
            "label": self.label,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "cache_creation_input_tokens": self.cache_creation_input_tokens,
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd(), 6),
        }


@dataclass
class UsageAggregator:
    """Collect per-call usage for one request, emit a single summary dict."""

    calls: List[LLMCall] = field(default_factory=list)

    def record(self, call: LLMCall) -> None:
        self.calls.append(call)

    def record_anthropic(self, label: str, model: str, usage: Any) -> LLMCall:
        """Convenience wrapper: build an LLMCall from an SDK usage obj and store.

        Returns the built call so the caller can log or inspect it.
        """
        call = LLMCall.from_anthropic_usage(label, model, usage)
        self.record(call)
        return call

    def summary(self) -> dict:
        """Return a JSON-friendly dict: per-call records + totals + total cost.

        Shape matches what `/query` returns as `api_usage` and what the
        monthly JSON store persists — so the same shape serves both the
        live response and historical analytics.
        """
        calls_out = [c.to_record() for c in self.calls]
        totals = {
            "input_tokens": sum(c.input_tokens for c in self.calls),
            "cache_creation_input_tokens": sum(
                c.cache_creation_input_tokens for c in self.calls
            ),
            "cache_read_input_tokens": sum(
                c.cache_read_input_tokens for c in self.calls
            ),
            "output_tokens": sum(c.output_tokens for c in self.calls),
        }
        total_cost = sum(c.cost_usd() for c in self.calls)
        return {
            "calls": calls_out,
            "totals": totals,
            "total_cost_usd": round(total_cost, 6),
        }
