"""Tests for the evidence sufficiency assessment gate.

These tests verify the three-metric system (top_score, coverage, separation)
that decides whether the bot should answer or refuse.
"""

from __future__ import annotations

import pytest

from backend.core.evidence_sufficiency import (
    EvidenceSignals,
    assess_evidence_sufficiency,
    contextual_suggestions,
    default_suggestions,
)
from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk


def _make_chunk(
    chunk_id: str = "DOC_001::c001",
    text: str = "Section 64 user identity verification",
    header: str | None = "Section 64 User identity verification",
    authority_weight: float = 10.0,
    source_type: str = "Act of Parliament",
    section_number: str | None = "64",
    location_pointer: str | None = "Section 64",
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
        location_pointer=location_pointer,
        authority_weight=authority_weight,
        section_number=section_number,
    )


def _make_candidate(chunk: KBChunk, score: float) -> RetrievedChunk:
    return RetrievedChunk(chunk=chunk, final_score=score, bm25_score=score)


# ── Empty candidates → always insufficient ──────────────────────────────

class TestEmptyCandidates:
    def test_no_candidates_returns_insufficient(self):
        signals = assess_evidence_sufficiency("What does section 64 say?", [])
        assert signals.status == "insufficient_evidence"
        assert signals.top_score == 0.0
        assert signals.coverage == 0.0
        assert signals.confidence_label == "low"


# ── Strong evidence → passes gate ────────────────────────────────────────

class TestStrongEvidence:
    def test_high_score_high_coverage_passes(self):
        """A clear top hit with good token coverage should be sufficient."""
        chunk = _make_chunk(text="Section 64 user identity verification provisions allow adult users to verify")
        candidates = [
            _make_candidate(chunk, score=0.9),
            _make_candidate(_make_chunk(chunk_id="DOC_001::c002", text="Other content", section_number=None), score=0.3),
        ]
        signals = assess_evidence_sufficiency("section 64 identity verification", candidates)
        assert signals.status == "ok"
        assert signals.top_score >= 0.35
        assert signals.confidence_label in ("high", "medium")

    def test_separation_matters(self):
        """When top two scores are nearly identical, separation is poor."""
        chunk_a = _make_chunk(chunk_id="DOC_001::c001", text="Section 64 identity")
        chunk_b = _make_chunk(chunk_id="DOC_001::c002", text="Section 65 identity")
        # Two candidates with very close scores → low separation
        candidates = [
            _make_candidate(chunk_a, score=0.40),
            _make_candidate(chunk_b, score=0.39),
        ]
        signals = assess_evidence_sufficiency("identity verification", candidates)
        # Separation = 0.40 / 0.39 ≈ 1.026, below the 1.2 threshold
        assert signals.separation < 1.2


# ── Section override ─────────────────────────────────────────────────────

class TestSectionOverride:
    def test_exact_section_match_overrides_low_scores(self):
        """Direct section match from high-authority source should override low metrics."""
        chunk = _make_chunk(
            text="Section 64 allows verification",
            header="Section 64 User identity verification",
            authority_weight=10.0,
            section_number="64",
        )
        candidates = [
            _make_candidate(chunk, score=0.20),  # Below top_score threshold of 0.35
        ]
        signals = assess_evidence_sufficiency("What does section 64 say?", candidates)
        # The section-match override should rescue this
        assert signals.status == "ok"

    def test_low_authority_section_match_no_override(self):
        """Section match from low-authority source should NOT override."""
        chunk = _make_chunk(
            text="Section 64 was discussed in the news",
            header="Section 64",
            authority_weight=3.0,  # Below the 8.0 threshold for override
            source_type="News Article",
            section_number="64",
        )
        candidates = [
            _make_candidate(chunk, score=0.20),
        ]
        signals = assess_evidence_sufficiency("What does section 64 say?", candidates)
        assert signals.status == "insufficient_evidence"


# ── Multi-source authority override ──────────────────────────────────────

class TestMultiSourceOverride:
    def test_multiple_act_chunks_plus_supporting_overrides(self):
        """2+ Act chunks and 5+ supporting chunks should override insufficiency."""
        act_chunks = [
            _make_candidate(
                _make_chunk(chunk_id=f"DOC_001::c{i:03d}", text=f"Act provision {i}", authority_weight=10.0),
                score=0.30,
            )
            for i in range(3)
        ]
        support_chunks = [
            _make_candidate(
                _make_chunk(
                    chunk_id=f"DOC_002::c{i:03d}",
                    text=f"Guidance note {i}",
                    authority_weight=5.0,
                    source_type="Consultation",
                    section_number=None,
                ),
                score=0.25,
            )
            for i in range(5)
        ]
        candidates = act_chunks + support_chunks
        signals = assess_evidence_sufficiency("provider duties for regulated services", candidates)
        assert signals.status == "ok"


# ── Confidence labels ────────────────────────────────────────────────────

class TestConfidenceLabels:
    def test_high_confidence_requires_strong_signals(self):
        chunk = _make_chunk(text="Section 64 identity verification for adult users")
        candidates = [
            _make_candidate(chunk, score=0.9),
            _make_candidate(_make_chunk(chunk_id="DOC_001::c002", text="Unrelated", section_number=None), score=0.1),
        ]
        signals = assess_evidence_sufficiency("section 64 identity verification", candidates)
        assert signals.confidence_label == "high"

    def test_low_confidence_on_poor_scores(self):
        chunk = _make_chunk(text="Something vaguely related", section_number=None)
        candidates = [_make_candidate(chunk, score=0.10)]
        signals = assess_evidence_sufficiency("encryption requirements", candidates)
        assert signals.confidence_label == "low"


# ── Contextual suggestions ───────────────────────────────────────────────

class TestContextualSuggestions:
    def test_comparison_query_gets_breakdown_suggestion(self):
        candidates = [
            _make_candidate(
                _make_chunk(text="User-to-user duties under section 11", location_pointer="Section 11"),
                score=0.3,
            ),
        ]
        message, suggestions = contextual_suggestions(
            "Compare user-to-user vs search service duties",
            candidates,
        )
        assert "comparison" in suggestions[0].lower() or "separately" in suggestions[0].lower()

    def test_empty_candidates_gives_defaults(self):
        message, suggestions = contextual_suggestions("anything", [])
        assert len(suggestions) >= 2
        assert "couldn't find" in message.lower()

    def test_disabled_filters_surfaced(self):
        chunk = _make_chunk(text="Some Act text")
        candidates = [_make_candidate(chunk, score=0.3)]
        message, suggestions = contextual_suggestions(
            "What does Ofcom guidance say?",
            candidates,
            active_categories=["Act"],
            all_categories=["Act", "Regulator Guidance", "Debates / Hansard"],
        )
        filter_suggestions = [s for s in suggestions if "filtered out" in s.lower() or "source" in s.lower()]
        assert len(filter_suggestions) >= 1
