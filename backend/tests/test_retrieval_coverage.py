"""Tests for retrieval_coverage metadata (Brief 9 sub-job C).

Honest framing: when retrieval-depth is the constraint (many chunks match
but only a few are in the pack), the LLM must frame limitations as a
retrieval problem, NOT as corpus sparsity. RetrievalCoverage carries the
metadata that lets it distinguish the two.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend import config
from backend.core.llm_synthesis import (
    _build_user_prompt,
    _build_system_prompt,
    _format_retrieval_metadata,
)
from backend.core.models import KBChunk, QueryFilters
from backend.core.query_flow import RetrievalCoverage, run_retrieval_plan
from backend.core.retriever import RetrievedChunk


def _candidate(doc_id: str, chunk_id: str, score: float) -> RetrievedChunk:
    chunk = KBChunk(
        doc_id=doc_id,
        title=f"{doc_id} Act",
        source_type="Act",
        publisher="UK Parliament",
        date_published="2023-10-26",
        chunk_id=chunk_id,
        chunk_text="Regulated service duties apply to user-to-user services " * 20,
        location_pointer=f"Section {chunk_id}",
        authority_weight=10.0,
    )
    return RetrievedChunk(chunk=chunk, final_score=score, bm25_score=score, embedding_score=None)


def _synthetic_candidates(n_docs: int, chunks_per_doc: int) -> list[RetrievedChunk]:
    total = n_docs * chunks_per_doc
    out: list[RetrievedChunk] = []
    for rank in range(total):
        doc_index = rank % n_docs
        chunk_index = rank // n_docs
        doc_id = f"DOC_{doc_index:03d}"
        chunk_id = f"{doc_id}::c{chunk_index:03d}"
        score = 1.0 - (rank / total) * 0.5
        out.append(_candidate(doc_id, chunk_id, score))
    return out


def _fake_retriever(candidates: list[RetrievedChunk], corpus_matches: int):
    kb = SimpleNamespace(get_chunk=lambda _id: None, chunks=[c.chunk for c in candidates])
    retriever = MagicMock()
    retriever.retrieve = MagicMock(return_value=candidates)
    retriever.kb = kb
    retriever.last_context = MagicMock(
        return_value={
            "corpus_matches": corpus_matches,
            "requested_top_k": len(candidates),
        }
    )
    return retriever


# ── RetrievalCoverage dataclass ─────────────────────────────────────────────

class TestRetrievalCoverage:
    def test_coverage_ratio_basic(self):
        c = RetrievalCoverage(
            requested=50, returned=50, pack_size=5, corpus_matches=500, kind="survey"
        )
        assert c.coverage_ratio == 0.01

    def test_coverage_ratio_zero_corpus_is_one(self):
        c = RetrievalCoverage(
            requested=50, returned=0, pack_size=0, corpus_matches=0, kind="factual"
        )
        assert c.coverage_ratio == 1.0
        assert c.is_retrieval_limited is False

    def test_is_retrieval_limited_when_pack_is_small_slice(self):
        c = RetrievalCoverage(
            requested=150, returned=150, pack_size=40, corpus_matches=500, kind="survey"
        )
        assert c.is_retrieval_limited is True

    def test_is_retrieval_limited_false_when_corpus_itself_sparse(self):
        c = RetrievalCoverage(
            requested=50, returned=3, pack_size=3, corpus_matches=3, kind="factual"
        )
        assert c.is_retrieval_limited is False

    def test_to_dict_contains_derived_fields(self):
        c = RetrievalCoverage(
            requested=150, returned=150, pack_size=40, corpus_matches=500, kind="survey"
        )
        d = c.to_dict()
        assert set(d.keys()) >= {
            "requested", "returned", "pack_size", "corpus_matches",
            "kind", "coverage_ratio", "is_retrieval_limited",
        }
        assert d["is_retrieval_limited"] is True

    def test_threshold_env_override_moves_the_line(self, monkeypatch):
        monkeypatch.setattr(config, "RETRIEVAL_LIMITED_COVERAGE_THRESHOLD", 0.5)
        c = RetrievalCoverage(
            requested=50, returned=50, pack_size=40, corpus_matches=100, kind="survey"
        )
        assert c.is_retrieval_limited is True
        monkeypatch.setattr(config, "RETRIEVAL_LIMITED_COVERAGE_THRESHOLD", 0.1)
        assert c.is_retrieval_limited is False


# ── run_retrieval_plan populates coverage ──────────────────────────────────

class TestRunRetrievalPlanCoverage:
    def test_survey_outcome_populates_retrieval_coverage(self):
        candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6)
        retriever = _fake_retriever(candidates, corpus_matches=500)
        out = run_retrieval_plan(
            "Main debates on online safety duties",
            QueryFilters(),
            retriever,
        )
        assert out.retrieval_coverage is not None
        cov = out.retrieval_coverage
        assert cov.kind == "survey"
        assert cov.corpus_matches == 500
        assert cov.pack_size == len(
            [c for c in out.evidence_pack if c.chunk_id not in out.expansion_ids]
        )
        assert cov.is_retrieval_limited is True

    def test_factual_outcome_populates_retrieval_coverage(self):
        candidates = _synthetic_candidates(n_docs=5, chunks_per_doc=2)
        retriever = _fake_retriever(candidates, corpus_matches=10)
        out = run_retrieval_plan(
            "What does Section 64 say?",
            QueryFilters(),
            retriever,
        )
        assert out.retrieval_coverage is not None
        assert out.retrieval_coverage.kind == "factual"


# ── Prompt formatting ──────────────────────────────────────────────────────

class TestPromptMetadataInjection:
    def test_user_prompt_carries_metadata_block_when_coverage_given(self):
        coverage = RetrievalCoverage(
            requested=150, returned=150, pack_size=40, corpus_matches=500, kind="survey"
        )
        prompt = _build_user_prompt(
            "Main debates", context="some chunks", coverage=coverage
        )
        assert "RETRIEVAL METADATA" in prompt
        assert "retrieval_coverage" in prompt
        assert '"corpus_matches": 500' in prompt
        assert '"kind": "survey"' in prompt
        # Question still present and framed.
        assert "QUESTION: Main debates" in prompt
        # Evidence still present.
        assert "EVIDENCE CHUNKS" in prompt
        assert "some chunks" in prompt

    def test_user_prompt_unchanged_when_coverage_none(self):
        """Backwards-compat: callers that don't thread coverage yet."""
        prompt = _build_user_prompt("q", context="ctx", coverage=None)
        assert "RETRIEVAL METADATA" not in prompt
        assert "EVIDENCE CHUNKS" in prompt
        assert "QUESTION: q" in prompt

    def test_format_retrieval_metadata_none_returns_empty_string(self):
        assert _format_retrieval_metadata(None) == ""

    def test_format_retrieval_metadata_serializes_json(self):
        coverage = RetrievalCoverage(
            requested=50, returned=50, pack_size=5, corpus_matches=500, kind="survey"
        )
        block = _format_retrieval_metadata(coverage)
        assert block.startswith("RETRIEVAL METADATA:\n")
        assert "retrieval_coverage: {" in block
        assert '"pack_size": 5' in block
        assert '"is_retrieval_limited": true' in block


class TestSystemPromptHonestFramingRule:
    def test_system_prompt_includes_honest_framing_rule_when_configured(self):
        prompt = _build_system_prompt()
        # Default copy references retrieval_coverage by name so the LLM can
        # find the metadata block in the user turn.
        assert "retrieval_coverage" in prompt
        # Says the corpus-vs-retrieval distinction the brief called out.
        assert "retrieval" in prompt.lower() and "corpus" in prompt.lower()

    def test_env_override_replaces_default_framing(self, monkeypatch):
        monkeypatch.setattr(
            config,
            "HONEST_FRAMING_SYSTEM_RULE",
            "RULE 9: A completely custom framing rule for testing.",
        )
        prompt = _build_system_prompt()
        assert "RULE 9: A completely custom framing rule for testing." in prompt

    def test_empty_env_override_drops_rule(self, monkeypatch):
        monkeypatch.setattr(config, "HONEST_FRAMING_SYSTEM_RULE", "")
        prompt = _build_system_prompt()
        assert "retrieval_coverage" not in prompt


class TestAcceptanceCriterionBriefC:
    """Named criterion: survey answer includes 'retrieval surfaced N of M'
    framing when retrieval_coverage < 20% of corpus_matches.
    """

    def test_retrieval_limited_flag_reaches_user_prompt(self):
        coverage = RetrievalCoverage(
            requested=150, returned=150, pack_size=40, corpus_matches=500, kind="survey"
        )
        assert coverage.is_retrieval_limited is True
        prompt = _build_user_prompt("q", context="c", coverage=coverage)
        assert '"is_retrieval_limited": true' in prompt

    def test_sparse_corpus_does_not_fire_retrieval_limited(self):
        coverage = RetrievalCoverage(
            requested=50, returned=4, pack_size=4, corpus_matches=4, kind="factual"
        )
        assert coverage.is_retrieval_limited is False
        prompt = _build_user_prompt("q", context="c", coverage=coverage)
        assert '"is_retrieval_limited": false' in prompt
