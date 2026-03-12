"""Tests for the refusal and query guard paths.

Verifies that:
- Out-of-scope queries are rejected
- Analytics queries are rejected
- In-scope queries pass through
- Evidence-based refusals work correctly
- The extractive answer generator refuses when evidence is empty
"""

from __future__ import annotations

import pytest

from backend.core.query_guard import QueryClassification, classify_query, has_definition_intent
from backend.core.evidence import (
    build_citations,
    build_evidence_pack,
    generate_answer,
    should_refuse,
)
from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk


def _make_chunk(
    chunk_id: str = "DOC_001::c001",
    text: str = "Section 64 user identity verification",
    header: str | None = "Section 64",
    authority_weight: float = 10.0,
    source_type: str = "Act of Parliament",
) -> KBChunk:
    return KBChunk(
        doc_id="DOC_001",
        title="Online Safety Act 2023",
        source_type=source_type,
        publisher="UK Parliament",
        date_published="2023-10-26",
        chunk_id=chunk_id,
        chunk_text=text,
        header=header,
        location_pointer="Section 64",
        authority_weight=authority_weight,
    )


def _make_candidate(chunk: KBChunk, score: float) -> RetrievedChunk:
    return RetrievedChunk(chunk=chunk, final_score=score, bm25_score=score)


# ── Query classification ─────────────────────────────────────────────────

class TestQueryClassification:
    def test_in_scope_with_act_reference(self):
        assert classify_query("What does the Online Safety Act say about illegal content?") == QueryClassification.IN_SCOPE

    def test_in_scope_with_section_reference(self):
        assert classify_query("What does section 64 require?") == QueryClassification.IN_SCOPE

    def test_in_scope_with_ofcom_reference(self):
        assert classify_query("What is Ofcom's role in enforcement?") == QueryClassification.IN_SCOPE

    def test_out_of_scope_weather(self):
        assert classify_query("What is the weather today?") == QueryClassification.OUT_OF_SCOPE

    def test_out_of_scope_football(self):
        assert classify_query("Who won the football?") == QueryClassification.OUT_OF_SCOPE

    def test_out_of_scope_capital(self):
        assert classify_query("What is the capital of France?") == QueryClassification.OUT_OF_SCOPE

    def test_analytics_how_many(self):
        assert classify_query("How many sections mention encryption?") == QueryClassification.UNSUPPORTED_ANALYTICS

    def test_analytics_count(self):
        assert classify_query("Count the references to child safety") == QueryClassification.UNSUPPORTED_ANALYTICS

    def test_analytics_top_n(self):
        assert classify_query("What are the top 5 most referenced topics?") == QueryClassification.UNSUPPORTED_ANALYTICS

    def test_analytics_frequency(self):
        assert classify_query("What is the frequency of the term risk assessment?") == QueryClassification.UNSUPPORTED_ANALYTICS


# ── Definition intent detection ──────────────────────────────────────────

class TestDefinitionIntent:
    def test_what_is_detected(self):
        assert has_definition_intent("What is a user-to-user service?") is True

    def test_define_detected(self):
        assert has_definition_intent("Define regulated service") is True

    def test_meaning_detected(self):
        assert has_definition_intent("What is the meaning of priority content?") is True

    def test_no_definition_intent(self):
        assert has_definition_intent("What duties apply to providers?") is False


# ── should_refuse ────────────────────────────────────────────────────────

class TestShouldRefuse:
    def test_refuses_empty_candidates(self):
        assert should_refuse([], []) is True

    def test_refuses_empty_evidence(self):
        chunk = _make_chunk()
        candidates = [_make_candidate(chunk, score=0.5)]
        assert should_refuse(candidates, []) is True

    def test_refuses_low_score(self):
        chunk = _make_chunk()
        candidates = [_make_candidate(chunk, score=0.10)]
        assert should_refuse(candidates, [chunk]) is True

    def test_accepts_good_score(self):
        chunk = _make_chunk()
        candidates = [_make_candidate(chunk, score=0.50)]
        assert should_refuse(candidates, [chunk]) is False


# ── generate_answer (extractive mode) ────────────────────────────────────

class TestGenerateAnswer:
    def test_empty_evidence_refuses(self):
        answer = generate_answer("What does section 64 say?", [], [])
        assert answer.refused is True
        assert "No relevant evidence" in answer.text

    def test_with_evidence_produces_answer(self):
        chunk = _make_chunk(text="Section 64 allows Category 1 service providers to offer identity verification.")
        citations = build_citations([chunk])
        answer = generate_answer("What does section 64 say?", [chunk], citations)
        assert answer.refused is False
        assert "C001" in answer.text

    def test_confidence_high_for_exact_section_match(self):
        chunk = _make_chunk(
            text="Section 64 user identity verification.",
            header="Section 64 User identity verification",
        )
        citations = build_citations([chunk])
        answer = generate_answer(
            "What does section 64 say?",
            [chunk],
            citations,
            target_section=64,
        )
        assert answer.confidence.level == "high"

    def test_confidence_low_for_no_evidence(self):
        answer = generate_answer("What does section 99 say?", [], [])
        assert answer.confidence.level == "low"


# ── build_evidence_pack ──────────────────────────────────────────────────

class TestBuildEvidencePack:
    def test_empty_candidates(self):
        assert build_evidence_pack([]) == []

    def test_filters_low_scoring(self):
        high = _make_candidate(_make_chunk(chunk_id="c001", text="High relevance"), score=1.0)
        low = _make_candidate(
            _make_chunk(chunk_id="c002", text="Very low relevance"),
            score=0.01,  # 1% of top → below 15% threshold
        )
        pack = build_evidence_pack([high, low])
        chunk_ids = [c.chunk_id for c in pack]
        assert "c001" in chunk_ids
        assert "c002" not in chunk_ids

    def test_deduplicates_by_doc_location(self):
        """Two chunks from same doc + same location pointer → only one kept."""
        chunk_a = _make_chunk(chunk_id="c001", text="First chunk about section 64")
        chunk_b = _make_chunk(chunk_id="c002", text="Second chunk about section 64")
        # Same doc_id and location_pointer
        candidates = [
            _make_candidate(chunk_a, score=0.9),
            _make_candidate(chunk_b, score=0.8),
        ]
        pack = build_evidence_pack(candidates)
        assert len(pack) == 1
