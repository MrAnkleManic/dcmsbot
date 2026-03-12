"""Tests for the section-lock guardrail.

Section lock filters retrieval candidates to only those matching a specific
section number when the query references one. This prevents irrelevant chunks
from diluting section-specific answers.
"""

from __future__ import annotations

import pytest

from backend.core.guardrails import apply_section_lock, SectionLockOutcome
from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk
from backend.core.sections import parse_target_section, chunk_section_number


def _make_chunk(
    chunk_id: str,
    text: str,
    header: str | None = None,
    section_number: str | None = None,
    location_pointer: str | None = None,
) -> KBChunk:
    return KBChunk(
        doc_id="DOC_001",
        title="Online Safety Act 2023",
        source_type="Act of Parliament",
        publisher="UK Parliament",
        date_published="2023-10-26",
        chunk_id=chunk_id,
        chunk_text=text,
        header=header,
        location_pointer=location_pointer or (f"Section {section_number}" if section_number else None),
        authority_weight=10.0,
        section_number=section_number,
    )


def _make_candidate(chunk: KBChunk, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(chunk=chunk, final_score=score, bm25_score=score)


# ── parse_target_section ─────────────────────────────────────────────────

class TestParseTargetSection:
    def test_section_64(self):
        assert parse_target_section("What does section 64 say?") == 64

    def test_section_abbreviation(self):
        assert parse_target_section("s.12 duties") == 12

    def test_section_with_subsection(self):
        assert parse_target_section("section 72(3)") == 72

    def test_no_section_returns_none(self):
        assert parse_target_section("What are provider duties?") is None

    def test_article_reference(self):
        assert parse_target_section("article 5 provisions") == 5


# ── chunk_section_number ─────────────────────────────────────────────────

class TestChunkSectionNumber:
    def test_extracts_from_header(self):
        chunk = _make_chunk("c001", "text", header="Section 64 User identity verification")
        assert chunk_section_number(chunk) == 64

    def test_extracts_from_location_pointer(self):
        chunk = _make_chunk("c001", "text", header=None, location_pointer="Section 12")
        assert chunk_section_number(chunk) == 12

    def test_no_section_returns_none(self):
        chunk = _make_chunk("c001", "text", header="Introduction", section_number=None, location_pointer="Page 1")
        assert chunk_section_number(chunk) is None


# ── apply_section_lock ───────────────────────────────────────────────────

class TestApplySectionLock:
    def setup_method(self):
        self.section_64_chunk = _make_chunk(
            "c064", "Section 64 user identity verification", header="Section 64 User identity verification", section_number="64"
        )
        self.section_12_chunk = _make_chunk(
            "c012", "Section 12 duties for illegal content", header="Section 12 Duties", section_number="12"
        )
        self.generic_chunk = _make_chunk(
            "c999", "General introduction text", header="Introduction", section_number=None, location_pointer="Page 1"
        )
        self.candidates = [
            _make_candidate(self.section_64_chunk, score=0.8),
            _make_candidate(self.section_12_chunk, score=0.7),
            _make_candidate(self.generic_chunk, score=0.6),
        ]

    def test_no_section_reference_passes_all_through(self):
        outcome = apply_section_lock("What are provider duties?", self.candidates)
        assert not outcome.active
        assert outcome.section_number is None
        assert len(outcome.filtered_candidates) == 3
        assert outcome.label == "off"

    def test_section_reference_filters_to_matching(self):
        outcome = apply_section_lock("What does section 64 say?", self.candidates)
        assert outcome.active
        assert outcome.section_number == 64
        assert outcome.has_matches
        assert len(outcome.filtered_candidates) == 1
        assert outcome.filtered_candidates[0].chunk.chunk_id == "c064"
        assert outcome.label == "s.64"

    def test_section_with_no_matches_falls_back_to_all(self):
        outcome = apply_section_lock("What does section 99 say?", self.candidates)
        assert outcome.active
        assert outcome.section_number == 99
        assert not outcome.has_matches
        # When no matches found, falls back to original candidates
        assert len(outcome.filtered_candidates) == 3

    def test_preserves_original_candidates(self):
        outcome = apply_section_lock("section 64", self.candidates)
        assert len(outcome.original_candidates) == 3
