"""Brief 11 — discriminative corpus_matches counter.

Brief 9 counted any chunk with BM25 > 0 as a "corpus match". For DCMS's
mixed-source corpus that would be meaningless (cross-corpus tokens like
"online", "safety", "act", "section" saturate BM25). The content-overlap
counter operates on a stopword set of question scaffolding + reporting
verbs + request verbs, leaving only topic-bearing tokens.
"""

from __future__ import annotations

import pytest

from backend.core.retriever import (
    _CORPUS_MATCH_STOPWORDS,
    _count_content_matches,
    _extract_content_tokens,
    _tokenize,
)


# ── Token extraction ───────────────────────────────────────────────────────

class TestExtractContentTokens:
    def test_strips_short_tokens(self):
        toks = _tokenize("What were any fines imposed?")
        content = _extract_content_tokens(toks)
        # "what" / "were" / "any" are all stopwords; short tokens also out.
        assert "fines" in content or "imposed" in content
        assert not any(t in content for t in ("what", "were", "any"))

    def test_strips_purely_numeric_tokens(self):
        toks = _tokenize("fines imposed in 2023")
        content = _extract_content_tokens(toks)
        assert "2023" not in content
        assert "fines" in content

    def test_strips_request_verbs_as_stopwords(self):
        toks = _tokenize("please draft a narrative for me")
        content = _extract_content_tokens(toks)
        # "draft" / "narrative" / "please" are request-shape words, not
        # topic words — all three should be filtered.
        assert content == []

    def test_strips_reporting_verbs_as_stopwords(self):
        toks = _tokenize("what was reported about enforcement mentioned in coverage")
        content = _extract_content_tokens(toks)
        # "reported" / "mentioned" / "coverage" scaffold references, not
        # topic. "enforcement" is the only content word.
        assert "enforcement" in content
        assert "reported" not in content
        assert "mentioned" not in content
        assert "coverage" not in content

    def test_preserves_topic_tokens_order(self):
        toks = _tokenize("Ofcom enforcement against platforms")
        content = _extract_content_tokens(toks)
        # Order preserved (after lowercasing).
        assert content == ["ofcom", "enforcement", "against", "platforms"]

    def test_collapses_duplicates(self):
        toks = _tokenize("enforcement enforcement enforcement enforcement")
        content = _extract_content_tokens(toks)
        assert content == ["enforcement"]

    def test_stopword_set_contains_dcms_scaffolding(self):
        # Pin critical members. If this list shrinks by accident the
        # corpus_matches number drifts back toward meaninglessness.
        for required in (
            "what", "were", "about", "report", "reported", "reporting",
            "draft", "narrative", "please", "covered", "mentioned",
        ):
            assert required in _CORPUS_MATCH_STOPWORDS


# ── Content-match counting ─────────────────────────────────────────────────

class TestCountContentMatches:
    @staticmethod
    def _sets(texts):
        return [frozenset(_tokenize(t)) for t in texts]

    def test_threshold_one_counts_any_token(self):
        chunk_sets = self._sets([
            "ofcom issued an enforcement notice",
            "section 64 discusses record-keeping",
            "weather forecast was pleasant",
            "ofcom code of practice on enforcement",
        ])
        indices = list(range(len(chunk_sets)))
        count = _count_content_matches(
            ["ofcom", "enforcement"], chunk_sets, indices, threshold=1
        )
        # chunks 0, 1 (has "section" but no topic tokens? "ofcom"/"enforcement"
        # missing from 1 — actually "section" but that's not in our needles)
        # Let me re-check: chunk 0 has "ofcom" and "enforcement" → match
        # chunk 1 has neither "ofcom" nor "enforcement" → no match
        # chunk 2 has neither → no match
        # chunk 3 has both "ofcom" and "enforcement" → match
        assert count == 2

    def test_threshold_two_requires_both_tokens(self):
        chunk_sets = self._sets([
            "ofcom issued an enforcement notice",
            "section 64 discusses ofcom's role",
            "weather forecast was pleasant",
            "ofcom code of practice on enforcement",
        ])
        indices = list(range(len(chunk_sets)))
        count = _count_content_matches(
            ["ofcom", "enforcement"], chunk_sets, indices, threshold=2
        )
        # chunks 0 and 3 have both tokens.
        assert count == 2

    def test_empty_content_tokens_returns_zero(self):
        chunk_sets = self._sets(["anything goes here"])
        assert _count_content_matches([], chunk_sets, [0], threshold=1) == 0

    def test_empty_index_set_returns_zero(self):
        chunk_sets = self._sets(["ofcom issued notice"])
        assert _count_content_matches(["ofcom"], chunk_sets, [], threshold=1) == 0

    def test_filtered_indices_respected(self):
        chunk_sets = self._sets([
            "ofcom",
            "ofcom",
            "nothing relevant",
        ])
        # Only chunks 0 and 2 are "in the filter"; chunk 1 skipped.
        count = _count_content_matches(["ofcom"], chunk_sets, [0, 2], threshold=1)
        assert count == 1


# ── End-to-end via Retriever ───────────────────────────────────────────────

class TestRetrieverCorpusMatchesIntegration:
    """Against a small hand-built KB, verify last_context carries the new
    fields (corpus_matches / corpus_match_method / content_tokens)."""

    @staticmethod
    def _chunk(doc_id: str, chunk_id: str, text: str, source_type: str = "Act"):
        from backend.core.models import KBChunk
        return KBChunk(
            doc_id=doc_id,
            chunk_id=chunk_id,
            chunk_text=text,
            title="t",
            source_type=source_type,
            publisher="UK Parliament",
            date_published="2023-10-26",
        )

    def test_retrieve_reports_discriminative_corpus_matches(self):
        from backend.core.loader import KnowledgeBase
        from backend.core.models import QueryFilters
        from backend.core.retriever import Retriever

        # Build a tiny corpus: 2 on-topic chunks, 3 off-topic. All share
        # the scaffolding word "section" so a BM25-floor-zero counter
        # would misreport 5/5.
        kb = KnowledgeBase()
        kb.chunks = [
            self._chunk("DOC_A", "c1", "Ofcom published enforcement guidance on section 10"),
            self._chunk("DOC_A", "c2", "Further Ofcom enforcement on section 11 duties"),
            self._chunk("DOC_B", "c3", "Shipping news covered in section 3"),
            self._chunk("DOC_C", "c4", "Commencement date for section 4"),
            self._chunk("DOC_D", "c5", "Weather report mentioning section 5"),
        ]
        retriever = Retriever(kb)
        retriever.build()
        retriever.retrieve("Ofcom enforcement actions", QueryFilters())
        ctx = retriever.last_context()
        assert ctx["corpus_match_method"].startswith("content-overlap>=")
        # content_tokens should preserve topic words (order, content-only).
        # "actions" is NOT a stopword in our DCMS set (we kept it topical),
        # while "ofcom" and "enforcement" clearly are topic.
        assert "ofcom" in ctx["content_tokens"]
        assert "enforcement" in ctx["content_tokens"]
        # chunks c1 + c2 contain both "ofcom" and "enforcement"; others don't.
        assert ctx["corpus_matches"] == 2

    def test_single_content_token_query_reports_matches(self):
        from backend.core.loader import KnowledgeBase
        from backend.core.models import QueryFilters
        from backend.core.retriever import Retriever

        kb = KnowledgeBase()
        kb.chunks = [
            self._chunk("DOC_A", "c1", "Ofcom has published an enforcement notice"),
            self._chunk("DOC_B", "c2", "Safer spaces online under the new duties"),
            self._chunk("DOC_C", "c3", "A second Ofcom enforcement action was announced"),
        ]
        retriever = Retriever(kb)
        retriever.build()
        retriever.retrieve("Were there any ofcom actions?", QueryFilters())
        ctx = retriever.last_context()
        # After stopword filtering: "ofcom", "actions" survive (neither is
        # in _CORPUS_MATCH_STOPWORDS). Threshold becomes ceil(2/2)=1 so
        # chunks containing either token count as matches.
        assert "ofcom" in ctx["content_tokens"]
        # chunks c1 + c3 have "ofcom"; c2 does not.
        assert ctx["corpus_matches"] >= 2
