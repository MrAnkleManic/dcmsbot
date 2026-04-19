"""Tests for LLM usage capture, pricing math, JSON store, and the
end-to-end `/query` wiring.

Backported from iln_bot@e5d042a. Test fixtures adapted to DCMS
source_types and queries.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.core.anthropic_pricing import (
    CACHE_READ_MULTIPLIER,
    CACHE_WRITE_MULTIPLIER,
    cost_usd,
    rate_for,
)
from backend.core.usage import LLMCall, UsageAggregator
from backend.core.usage_store import (
    append_usage_record,
    get_usage_summary,
)


# ---------------------------------------------------------------------------
# Pricing math
# ---------------------------------------------------------------------------

def test_cost_usd_applies_cache_multipliers() -> None:
    """Cache-write is 1.25x base input, cache-read is 0.1x base input."""
    model = "claude-sonnet-4-6"
    rate = rate_for(model)
    assert cost_usd(model, input_tokens=1_000_000) == pytest.approx(3.00)
    assert cost_usd(
        model, cache_creation_input_tokens=1_000_000
    ) == pytest.approx(3.00 * CACHE_WRITE_MULTIPLIER)
    assert cost_usd(
        model, cache_read_input_tokens=1_000_000
    ) == pytest.approx(3.00 * CACHE_READ_MULTIPLIER)
    assert cost_usd(model, output_tokens=1_000_000) == pytest.approx(15.00)
    assert rate["input_per_mtok"] == 3.00
    assert rate["output_per_mtok"] == 15.00


def test_cost_usd_unknown_model_falls_back_to_sonnet() -> None:
    assert cost_usd(
        "some-future-model", input_tokens=1_000_000
    ) == pytest.approx(3.00)


def test_cost_usd_haiku_cheaper_than_sonnet() -> None:
    assert cost_usd(
        "claude-haiku-4-5-20251001", input_tokens=1_000_000
    ) == pytest.approx(0.80)
    assert cost_usd(
        "claude-haiku-4-5-20251001", output_tokens=1_000_000
    ) == pytest.approx(4.00)


# ---------------------------------------------------------------------------
# Aggregator (unit)
# ---------------------------------------------------------------------------

def _mock_usage(
    input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    output_tokens: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        input_tokens=input_tokens,
        cache_creation_input_tokens=cache_creation_input_tokens,
        cache_read_input_tokens=cache_read_input_tokens,
        output_tokens=output_tokens,
    )


def test_aggregator_captures_single_call_with_cache_fields() -> None:
    agg = UsageAggregator()
    agg.record_anthropic(
        label="synthesis",
        model="claude-sonnet-4-6",
        usage=_mock_usage(
            input_tokens=300,
            cache_creation_input_tokens=1100,
            cache_read_input_tokens=0,
            output_tokens=250,
        ),
    )
    summary = agg.summary()
    assert len(summary["calls"]) == 1
    call = summary["calls"][0]
    assert call["label"] == "synthesis"
    assert call["cache_creation_input_tokens"] == 1100
    assert call["cache_read_input_tokens"] == 0
    expected = (300 * 3 + 1100 * 3 * 1.25 + 250 * 15) / 1_000_000
    assert call["cost_usd"] == pytest.approx(round(expected, 6))
    assert summary["total_cost_usd"] == pytest.approx(round(expected, 6))


def test_aggregator_totals_across_multiple_calls() -> None:
    agg = UsageAggregator()
    agg.record_anthropic(
        "synthesis",
        "claude-sonnet-4-6",
        _mock_usage(input_tokens=200, cache_creation_input_tokens=1100, output_tokens=150),
    )
    agg.record_anthropic(
        "synthesis",
        "claude-sonnet-4-6",
        _mock_usage(input_tokens=200, cache_read_input_tokens=1100, output_tokens=150),
    )
    agg.record_anthropic(
        "rewriter",
        "claude-sonnet-4-6",
        _mock_usage(input_tokens=80, output_tokens=30),
    )
    summary = agg.summary()
    assert len(summary["calls"]) == 3
    totals = summary["totals"]
    assert totals["input_tokens"] == 480
    assert totals["cache_creation_input_tokens"] == 1100
    assert totals["cache_read_input_tokens"] == 1100
    assert totals["output_tokens"] == 330
    assert summary["calls"][1]["cost_usd"] < summary["calls"][0]["cost_usd"]


def test_aggregator_handles_none_cache_fields_from_old_sdk() -> None:
    """Anthropic returns None for cache fields on non-cached responses.
    The aggregator must coerce those to 0."""
    agg = UsageAggregator()
    agg.record_anthropic(
        "synthesis",
        "claude-sonnet-4-6",
        SimpleNamespace(
            input_tokens=100,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=None,
            output_tokens=50,
        ),
    )
    summary = agg.summary()
    assert summary["totals"]["cache_creation_input_tokens"] == 0
    assert summary["totals"]["cache_read_input_tokens"] == 0


def test_aggregator_empty_yields_zero_totals() -> None:
    summary = UsageAggregator().summary()
    assert summary["calls"] == []
    assert summary["total_cost_usd"] == 0.0
    assert summary["totals"] == {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }


# ---------------------------------------------------------------------------
# JSON store (tmp_path)
# ---------------------------------------------------------------------------

def _fake_summary(cost: float = 0.0123, model: str = "claude-sonnet-4-6") -> dict:
    return {
        "calls": [
            {
                "label": "synthesis",
                "model": model,
                "input_tokens": 200,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1100,
                "output_tokens": 150,
                "cost_usd": cost,
            }
        ],
        "totals": {
            "input_tokens": 200,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1100,
            "output_tokens": 150,
        },
        "total_cost_usd": cost,
    }


def test_append_usage_record_creates_monthly_file(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)
    append_usage_record(
        request_id="req-1",
        query_text="What does section 9 of the Online Safety Act require?",
        summary=_fake_summary(),
        timestamp=ts,
        store_dir=tmp_path,
    )
    month_file = tmp_path / "2026-04.json"
    assert month_file.exists()
    records = json.loads(month_file.read_text())
    assert len(records) == 1
    rec = records[0]
    assert rec["request_id"] == "req-1"
    assert rec["query_text"].startswith("What does section 9")
    assert rec["total_cost_usd"] == pytest.approx(0.0123)
    assert rec["calls"][0]["cache_read_input_tokens"] == 1100


def test_append_usage_record_concatenates_within_month(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 19, 10, 0, 0, tzinfo=timezone.utc)
    append_usage_record(
        request_id="req-1",
        query_text="Q1",
        summary=_fake_summary(0.001),
        timestamp=ts,
        store_dir=tmp_path,
    )
    append_usage_record(
        request_id="req-2",
        query_text="Q2",
        summary=_fake_summary(0.002),
        timestamp=ts.replace(hour=11),
        store_dir=tmp_path,
    )
    records = json.loads((tmp_path / "2026-04.json").read_text())
    assert [r["request_id"] for r in records] == ["req-1", "req-2"]


def test_append_usage_record_separates_months(tmp_path: Path) -> None:
    april = datetime(2026, 4, 30, 23, 59, 0, tzinfo=timezone.utc)
    may = datetime(2026, 5, 1, 0, 1, 0, tzinfo=timezone.utc)
    append_usage_record(
        request_id="r-apr",
        query_text="Q",
        summary=_fake_summary(0.01),
        timestamp=april,
        store_dir=tmp_path,
    )
    append_usage_record(
        request_id="r-may",
        query_text="Q",
        summary=_fake_summary(0.02),
        timestamp=may,
        store_dir=tmp_path,
    )
    assert (tmp_path / "2026-04.json").exists()
    assert (tmp_path / "2026-05.json").exists()


def test_get_usage_summary_aggregates_across_range(tmp_path: Path) -> None:
    append_usage_record(
        request_id="r1",
        query_text="Q1",
        summary=_fake_summary(0.001, model="claude-sonnet-4-6"),
        timestamp=datetime(2026, 4, 5, 12, 0, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    append_usage_record(
        request_id="r2",
        query_text="Q2",
        summary=_fake_summary(0.002, model="claude-sonnet-4-6"),
        timestamp=datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    append_usage_record(
        request_id="r3",
        query_text="Q3",
        summary=_fake_summary(0.003, model="claude-haiku-4-5-20251001"),
        timestamp=datetime(2026, 5, 2, 12, 0, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    summary = get_usage_summary(
        since=datetime(2026, 4, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 31, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    assert summary["request_count"] == 3
    assert summary["total_cost_usd"] == pytest.approx(0.006)
    assert set(summary["per_model"].keys()) == {
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
    }
    sonnet = summary["per_model"]["claude-sonnet-4-6"]
    assert sonnet["call_count"] == 2
    assert sonnet["cost_usd"] == pytest.approx(0.003)
    haiku = summary["per_model"]["claude-haiku-4-5-20251001"]
    assert haiku["call_count"] == 1
    assert haiku["cost_usd"] == pytest.approx(0.003)


def test_get_usage_summary_filters_by_timestamp(tmp_path: Path) -> None:
    append_usage_record(
        request_id="r-early",
        query_text="Q",
        summary=_fake_summary(0.010),
        timestamp=datetime(2026, 4, 1, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    append_usage_record(
        request_id="r-late",
        query_text="Q",
        summary=_fake_summary(0.020),
        timestamp=datetime(2026, 4, 20, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    summary = get_usage_summary(
        since=datetime(2026, 4, 10, tzinfo=timezone.utc),
        until=datetime(2026, 4, 30, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    assert summary["request_count"] == 1
    assert summary["total_cost_usd"] == pytest.approx(0.020)


# ---------------------------------------------------------------------------
# Integration — one /query call produces correct api_usage + store record
# ---------------------------------------------------------------------------

def _sample_kb_chunk():
    from backend.core.models import KBChunk
    return KBChunk(
        doc_id="DOC_OSA",
        title="Online Safety Act 2023",
        source_type="Act",
        publisher="HMSO",
        date_published="2023-10-26",
        chunk_id="DOC_OSA_0009",
        chunk_text="Section 9 imposes the illegal-content risk-assessment duty on user-to-user services.",
        location_pointer="Section 9",
        authority_weight=10.0,
    )


def test_query_attaches_api_usage_and_persists_record(tmp_path, monkeypatch) -> None:
    """End-to-end: a mocked /query call should

    (a) return `api_usage` in the response with the expected shape + cost,
    (b) append one record to the monthly JSON store.
    """
    from backend import app as app_module
    from backend.core.evidence_sufficiency import EvidenceSignals
    from backend.core.models import (
        QueryRequest,
    )
    from backend.core.query_flow import RetrievalOutcome
    from backend.core.query_guard import QueryClassification
    from backend.core.retriever import RetrievedChunk
    import backend.core.usage_store as usage_store_module

    monkeypatch.setattr(usage_store_module, "DEFAULT_STORE_DIR", tmp_path)

    def _patched_append(*, request_id, query_text, summary, timestamp=None):
        return usage_store_module.append_usage_record(
            request_id=request_id,
            query_text=query_text,
            summary=summary,
            timestamp=timestamp,
            store_dir=tmp_path,
        )
    monkeypatch.setattr(app_module, "append_usage_record", _patched_append)

    fake_usage = SimpleNamespace(
        input_tokens=180,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=1200,
        output_tokens=220,
    )
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="Section 9 [C001] sets the illegal-content risk-assessment duty.")],
        usage=fake_usage,
    )

    chunk = _sample_kb_chunk()
    candidate = RetrievedChunk(
        chunk=chunk, final_score=2.0, bm25_score=2.0, embedding_score=None,
    )
    retrieval_outcome = RetrievalOutcome(
        candidates=[candidate],
        evidence_pack=[chunk],
        top_score=2.0,
        definition_mode=False,
        used_definition_candidates=False,
        definition_candidates=None,
    )
    section_lock = SimpleNamespace(
        active=False,
        filtered_candidates=[candidate],
        has_matches=False,
        section_number=None,
        label="off",
    )

    with (
        patch.object(app_module, "classify_query", return_value=QueryClassification.IN_SCOPE),
        patch.object(app_module, "run_retrieval_plan", return_value=retrieval_outcome),
        patch.object(app_module, "apply_section_lock", return_value=section_lock),
        patch.object(
            app_module,
            "assess_evidence_sufficiency",
            return_value=EvidenceSignals(
                status="ok",
                top_score=2.0,
                coverage=1.0,
                separation=2.0,
                confidence_label="high",
            ),
        ),
        patch.object(app_module, "should_refuse", return_value=False),
        patch.object(app_module, "needs_parliament_data", return_value=False),
        patch.object(app_module.config, "llm_configured", return_value=True),
        patch.object(app_module.config, "ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        patch("backend.core.llm_synthesis.anthropic.Anthropic") as anthropic_cls,
    ):
        anthropic_cls.return_value.messages.create.return_value = fake_response

        req = QueryRequest(question="What does section 9 of the OSA require?", use_llm=True)
        resp = app_module.query(req)

    assert resp.api_usage is not None
    assert len(resp.api_usage["calls"]) == 1
    synth_call = resp.api_usage["calls"][0]
    assert synth_call["label"] == "synthesis"
    assert synth_call["model"] == "claude-sonnet-4-6"
    assert synth_call["cache_read_input_tokens"] == 1200
    expected_cost = (180 * 3 + 1200 * 3 * 0.1 + 220 * 15) / 1_000_000
    assert synth_call["cost_usd"] == pytest.approx(round(expected_cost, 6))
    assert resp.api_usage["total_cost_usd"] == pytest.approx(round(expected_cost, 6))

    month_files = list(tmp_path.glob("*.json"))
    assert len(month_files) == 1, f"expected one month file, found {month_files}"
    records = json.loads(month_files[0].read_text())
    assert len(records) == 1
    stored = records[0]
    assert stored["query_text"] == "What does section 9 of the OSA require?"
    assert stored["total_cost_usd"] == pytest.approx(round(expected_cost, 6))
    assert stored["calls"][0]["cache_read_input_tokens"] == 1200


def test_query_scope_refusal_attaches_zero_usage_and_no_store_write(
    tmp_path, monkeypatch,
) -> None:
    """Scope-guard refusals never hit the API — api_usage is present but
    zero, and nothing should be appended to the store."""
    from backend import app as app_module
    from backend.core.models import QueryRequest
    from backend.core.query_guard import QueryClassification
    import backend.core.usage_store as usage_store_module

    monkeypatch.setattr(usage_store_module, "DEFAULT_STORE_DIR", tmp_path)

    with patch.object(
        app_module, "classify_query", return_value=QueryClassification.OUT_OF_SCOPE
    ):
        req = QueryRequest(question="What is the stock price of NVDA today?", use_llm=True)
        resp = app_module.query(req)

    assert resp.api_usage is not None
    assert resp.api_usage["calls"] == []
    assert resp.api_usage["total_cost_usd"] == 0.0
    assert list(tmp_path.iterdir()) == [], "no store write expected on scope refusal"
