"""Tests for the persistent Q&A archive store. Backported from
iln_bot@441fdb0; fixtures adapted to DCMS (Online Safety Act) corpus."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.core.answers_store import (
    SCHEMA_VERSION,
    append_answer_record,
    list_answers,
    load_answer_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_answer(text: str = "Section 9 [C001] imposes the illegal-content risk-assessment duty.") -> dict:
    return {
        "text": text,
        "confidence": {"level": "high", "reason": "Top score 2.0"},
        "refused": False,
        "refusal_reason": None,
        "section_lock": "off",
        "allow_citations_on_refusal": False,
    }


def _minimal_citation(cid: str = "C001") -> dict:
    return {
        "citation_id": cid,
        "doc_id": "DOC_OSA",
        "title": "Online Safety Act 2023",
        "source_type": "Act",
        "publisher": "HMSO",
        "date_published": "2023-10-26",
        "location_pointer": "Section 9",
        "chunk_id": "DOC_OSA_0009",
        "excerpt": "Risk-assessment duty \u2026",
        "authority_weight": 10.0,
    }


def _minimal_chunk() -> dict:
    return {
        "doc_id": "DOC_OSA",
        "title": "Online Safety Act 2023",
        "source_type": "Act",
        "publisher": "HMSO",
        "date_published": "2023-10-26",
        "chunk_id": "DOC_OSA_0009",
        "chunk_text": "Section 9 imposes the illegal-content risk-assessment duty on user-to-user services.",
        "location_pointer": "Section 9",
        "authority_weight": 10.0,
    }


def _fake_usage(cost: float = 0.02) -> dict:
    return {
        "calls": [
            {
                "label": "synthesis", "model": "claude-sonnet-4-6",
                "input_tokens": 500, "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 1100, "output_tokens": 200,
                "cost_usd": cost,
            },
        ],
        "totals": {
            "input_tokens": 500, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 1100, "output_tokens": 200,
        },
        "total_cost_usd": cost,
    }


# ---------------------------------------------------------------------------
# Append / read round-trip
# ---------------------------------------------------------------------------

def test_append_writes_one_file_per_request(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 19, 10, 30, tzinfo=timezone.utc)
    rec = append_answer_record(
        request_id="44cdc155-19ed-4092-b6e9-93f35d7affb6",
        query_text="What does section 9 of the OSA require?",
        answer=_minimal_answer(),
        citations=[_minimal_citation()],
        evidence_pack=[_minimal_chunk()],
        api_usage=_fake_usage(),
        timestamp=ts,
        store_dir=tmp_path,
    )
    expected = tmp_path / "2026-04" / "44cdc155-19ed-4092-b6e9-93f35d7affb6.json"
    assert expected.exists()

    on_disk = json.loads(expected.read_text())
    assert on_disk == rec
    assert on_disk["schema_version"] == SCHEMA_VERSION
    assert on_disk["answer_text"] == rec["answer"]["text"]
    assert on_disk["api_usage"]["total_cost_usd"] == 0.02


def test_append_is_idempotent_on_request_id(tmp_path: Path) -> None:
    """Re-appending the same request_id must not overwrite the first record."""
    ts = datetime(2026, 4, 19, 10, 30, tzinfo=timezone.utc)
    first = append_answer_record(
        request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        query_text="first",
        answer=_minimal_answer("first answer"),
        citations=[],
        evidence_pack=[],
        timestamp=ts,
        store_dir=tmp_path,
    )
    second = append_answer_record(
        request_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        query_text="second attempt",
        answer=_minimal_answer("second answer"),
        citations=[],
        evidence_pack=[],
        timestamp=ts.replace(hour=11),
        store_dir=tmp_path,
    )
    assert first["answer_text"] == "first answer"
    assert second["answer_text"] == "first answer", "dedup by request_id must preserve original"
    month_dir = tmp_path / "2026-04"
    assert len(list(month_dir.iterdir())) == 1


def test_load_returns_none_for_unknown_id(tmp_path: Path) -> None:
    assert load_answer_record("11111111-2222-3333-4444-555555555555", store_dir=tmp_path) is None


def test_load_roundtrips_full_record(tmp_path: Path) -> None:
    ts = datetime(2026, 4, 19, 10, 30, tzinfo=timezone.utc)
    append_answer_record(
        request_id="c0ffee00-1111-2222-3333-444455556666",
        query_text="Q",
        answer=_minimal_answer(),
        citations=[_minimal_citation()],
        evidence_pack=[_minimal_chunk()],
        api_usage=None,
        timestamp=ts,
        store_dir=tmp_path,
    )
    got = load_answer_record("c0ffee00-1111-2222-3333-444455556666", store_dir=tmp_path)
    assert got is not None
    assert got["api_usage"] is None
    assert got["citations"][0]["citation_id"] == "C001"
    assert got["evidence_pack"][0]["chunk_id"] == "DOC_OSA_0009"


def test_invalid_request_id_rejected(tmp_path: Path) -> None:
    """Path-traversal defence: only hex/dash characters allowed."""
    with pytest.raises(ValueError):
        append_answer_record(
            request_id="../../../etc/passwd",
            query_text="Q",
            answer=_minimal_answer(),
            citations=[],
            evidence_pack=[],
            store_dir=tmp_path,
        )
    with pytest.raises(ValueError):
        load_answer_record("../../evil", store_dir=tmp_path)


# ---------------------------------------------------------------------------
# list_answers — filters + sort order
# ---------------------------------------------------------------------------

def _seed_archive(tmp_path: Path) -> None:
    """Five records across three months."""
    fixed_timestamps = [
        (datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
         "11111111-1111-1111-1111-111111111111", "Section 9 illegal-content duties"),
        (datetime(2026, 1, 20, 10, 0, tzinfo=timezone.utc),
         "22222222-2222-2222-2222-222222222222", "What did Ofcom say about ENFORCEMENT?"),
        (datetime(2026, 2, 10, 10, 0, tzinfo=timezone.utc),
         "33333333-3333-3333-3333-333333333333", "section 65 enforcement notices"),
        (datetime(2026, 2, 12, 10, 0, tzinfo=timezone.utc),
         "44444444-4444-4444-4444-444444444444", "Hansard committee oversight"),
        (datetime(2026, 3, 15, 10, 0, tzinfo=timezone.utc),
         "55555555-5555-5555-5555-555555555555", "Parliament debates on duties"),
    ]
    for ts, rid, q in fixed_timestamps:
        append_answer_record(
            request_id=rid,
            query_text=q,
            answer=_minimal_answer(f"answer for {q}"),
            citations=[],
            evidence_pack=[],
            api_usage=_fake_usage(0.01),
            timestamp=ts,
            store_dir=tmp_path,
        )


def test_list_returns_newest_first(tmp_path: Path) -> None:
    _seed_archive(tmp_path)
    results = list_answers(store_dir=tmp_path)
    assert len(results) == 5
    timestamps = [r["timestamp"] for r in results]
    assert timestamps == sorted(timestamps, reverse=True)
    assert results[0]["query_text"] == "Parliament debates on duties"


def test_list_applies_limit(tmp_path: Path) -> None:
    _seed_archive(tmp_path)
    top2 = list_answers(store_dir=tmp_path, limit=2)
    assert len(top2) == 2
    assert top2[0]["query_text"] == "Parliament debates on duties"


def test_list_filters_by_date_range(tmp_path: Path) -> None:
    _seed_archive(tmp_path)
    results = list_answers(
        since=datetime(2026, 2, 1, tzinfo=timezone.utc),
        until=datetime(2026, 2, 28, 23, 59, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    assert len(results) == 2
    assert {r["query_text"] for r in results} == {
        "section 65 enforcement notices",
        "Hansard committee oversight",
    }


def test_list_substring_filter_case_insensitive(tmp_path: Path) -> None:
    _seed_archive(tmp_path)
    # "enforcement" matches the Ofcom (caps) and the section-65 record.
    results = list_answers(store_dir=tmp_path, q="enforcement")
    assert len(results) == 2

    # "section" matches two records across different months
    results = list_answers(store_dir=tmp_path, q="section")
    assert len(results) == 2


def test_list_summary_shape(tmp_path: Path) -> None:
    append_answer_record(
        request_id="abcdef01-2345-6789-abcd-ef0123456789",
        query_text="Q",
        answer=_minimal_answer("Short answer."),
        citations=[],
        evidence_pack=[],
        api_usage=_fake_usage(0.0042),
        timestamp=datetime(2026, 4, 19, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    results = list_answers(store_dir=tmp_path)
    assert len(results) == 1
    summary = results[0]
    assert set(summary.keys()) == {
        "request_id", "timestamp", "query_text",
        "answer_preview", "refused", "total_cost_usd",
    }
    assert summary["total_cost_usd"] == pytest.approx(0.0042)
    assert summary["refused"] is False
    assert summary["answer_preview"] == "Short answer."


def test_list_truncates_long_preview(tmp_path: Path) -> None:
    long_text = "lorem ipsum " * 50
    append_answer_record(
        request_id="abcdef01-2345-6789-abcd-ef0123456780",
        query_text="Q",
        answer=_minimal_answer(long_text),
        citations=[],
        evidence_pack=[],
        timestamp=datetime(2026, 4, 19, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    results = list_answers(store_dir=tmp_path)
    preview = results[0]["answer_preview"]
    assert preview.endswith("\u2026")
    assert len(preview) <= 201


def test_list_empty_store_returns_empty_list(tmp_path: Path) -> None:
    assert list_answers(store_dir=tmp_path) == []


def test_refused_answer_flagged_in_summary(tmp_path: Path) -> None:
    refused_answer = {
        **_minimal_answer("I cannot answer this from the corpus."),
        "refused": True,
        "refusal_reason": "Out of scope.",
    }
    append_answer_record(
        request_id="99999999-9999-9999-9999-999999999999",
        query_text="What's the stock price?",
        answer=refused_answer,
        citations=[],
        evidence_pack=[],
        timestamp=datetime(2026, 4, 19, tzinfo=timezone.utc),
        store_dir=tmp_path,
    )
    [summary] = list_answers(store_dir=tmp_path)
    assert summary["refused"] is True


# ---------------------------------------------------------------------------
# /query → archive hook + /answers routes (integration)
# ---------------------------------------------------------------------------

def test_query_persists_to_archive_and_answers_route_returns_it(tmp_path, monkeypatch) -> None:
    """End-to-end: one /query call lands in the archive store with the right
    shape, /answers returns a matching summary, /answers/{id} returns the
    full record. Path redirection happens in the autouse `conftest` fixture.
    """
    from types import SimpleNamespace
    from unittest.mock import patch

    from backend import app as app_module
    from backend.core.evidence_sufficiency import EvidenceSignals
    from backend.core.models import QueryRequest, KBChunk
    from backend.core.query_flow import RetrievalOutcome
    from backend.core.query_guard import QueryClassification
    from backend.core.retriever import RetrievedChunk

    archive_dir = tmp_path / "answers"

    fake_usage = SimpleNamespace(
        input_tokens=180, cache_creation_input_tokens=0,
        cache_read_input_tokens=1200, output_tokens=220,
    )
    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="Section 9 [C001] sets the illegal-content risk-assessment duty.")],
        usage=fake_usage,
    )
    chunk = KBChunk(
        doc_id="DOC_OSA", title="Online Safety Act 2023",
        source_type="Act", publisher="HMSO",
        date_published="2023-10-26",
        chunk_id="DOC_OSA_0009",
        chunk_text="Section 9 imposes the illegal-content risk-assessment duty.",
        location_pointer="Section 9",
        authority_weight=10.0,
    )
    candidate = RetrievedChunk(chunk=chunk, final_score=2.0, bm25_score=2.0, embedding_score=None)
    retrieval_outcome = RetrievalOutcome(
        candidates=[candidate], evidence_pack=[chunk],
        top_score=2.0, definition_mode=False,
        used_definition_candidates=False, definition_candidates=None,
    )
    section_lock = SimpleNamespace(
        active=False, filtered_candidates=[candidate],
        has_matches=False, section_number=None, label="off",
    )

    with (
        patch.object(app_module, "classify_query", return_value=QueryClassification.IN_SCOPE),
        patch.object(app_module, "run_retrieval_plan", return_value=retrieval_outcome),
        patch.object(app_module, "apply_section_lock", return_value=section_lock),
        patch.object(
            app_module, "assess_evidence_sufficiency",
            return_value=EvidenceSignals(
                status="ok", top_score=2.0, coverage=1.0,
                separation=2.0, confidence_label="high",
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

    month_dirs = [p for p in archive_dir.iterdir() if p.is_dir()]
    assert len(month_dirs) == 1
    record_files = list(month_dirs[0].glob("*.json"))
    assert len(record_files) == 1
    stored = json.loads(record_files[0].read_text())
    assert stored["schema_version"] == SCHEMA_VERSION
    assert stored["query_text"] == "What does section 9 of the OSA require?"
    assert stored["answer_text"].startswith("Section 9")
    assert stored["answer"]["refused"] is False
    assert stored["citations"]
    assert stored["evidence_pack"][0]["chunk_id"] == "DOC_OSA_0009"
    assert stored["api_usage"]["total_cost_usd"] == resp.api_usage["total_cost_usd"]

    archive_list = app_module.answers_list()
    assert archive_list.count == 1
    summary = archive_list.results[0]
    assert summary.request_id == stored["request_id"]
    assert summary.query_text == stored["query_text"]
    assert summary.total_cost_usd == stored["api_usage"]["total_cost_usd"]

    got = app_module.answers_get(stored["request_id"])
    assert got == stored

    filtered = app_module.answers_list(q="section 9")
    assert filtered.count == 1
    empty = app_module.answers_list(q="nonexistent")
    assert empty.count == 0


def test_answers_get_404s_unknown_id() -> None:
    from fastapi import HTTPException
    from backend import app as app_module

    with pytest.raises(HTTPException) as excinfo:
        app_module.answers_get("deadbeef-0000-0000-0000-000000000000")
    assert excinfo.value.status_code == 404


def test_answers_list_rejects_malformed_date() -> None:
    from fastapi import HTTPException
    from backend import app as app_module

    with pytest.raises(HTTPException) as excinfo:
        app_module.answers_list(since="not-a-date")
    assert excinfo.value.status_code == 400
