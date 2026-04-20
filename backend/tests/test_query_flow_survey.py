"""Integration test for run_retrieval_plan survey-widening (Brief 9 sub-job A).

Confirms the wiring: a survey question flows through classify_query_kind
→ SURVEY pack config → widened top_k to the retriever → widened caps to
build_evidence_pack. A factual question preserves the pre-Brief-9
behaviour.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend import config
from backend.core.models import KBChunk, QueryFilters
from backend.core.query_flow import run_retrieval_plan
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


def _fake_retriever(candidates: list[RetrievedChunk], corpus_matches: int = 0):
    """Build a minimal Retriever-shaped object returning the given candidates.

    The real Retriever is heavy (BM25 + embeddings). We only need
    retrieve() and .kb for expand_with_neighbors; the kb returns None for
    any neighbour lookup so expansion is a no-op.
    """
    kb = SimpleNamespace(get_chunk=lambda _id: None, chunks=[c.chunk for c in candidates])
    retriever = MagicMock()
    retriever.retrieve = MagicMock(return_value=candidates)
    retriever.kb = kb
    retriever.last_context = MagicMock(
        return_value={"corpus_matches": corpus_matches, "requested_top_k": len(candidates)}
    )
    return retriever


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


def test_survey_question_widens_top_k_and_pack() -> None:
    candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6)
    retriever = _fake_retriever(candidates, corpus_matches=500)
    filters = QueryFilters()

    outcome = run_retrieval_plan(
        "What are the main debates on online safety duties?",
        filters,
        retriever,
    )

    assert outcome.query_kind.kind == "survey"
    # Retriever called with the widened top_k.
    retriever.retrieve.assert_called_once()
    _, kwargs = retriever.retrieve.call_args
    assert kwargs.get("top_k") == config.SURVEY_RETRIEVAL_TOP_K
    # Widened pack: more chunks than the default per-source-type cap.
    primaries = outcome.evidence_pack
    assert len(primaries) > config.MAX_CHUNKS_PER_SOURCE_TYPE
    distinct_docs = {c.doc_id for c in primaries}
    assert len(distinct_docs) >= 5


def test_factual_question_preserves_default_behaviour() -> None:
    candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6)
    retriever = _fake_retriever(candidates, corpus_matches=30)
    filters = QueryFilters()

    outcome = run_retrieval_plan(
        "What does Section 64 of the Online Safety Act say?",
        filters,
        retriever,
    )

    assert outcome.query_kind.kind == "factual"
    _, kwargs = retriever.retrieve.call_args
    assert kwargs.get("top_k") == config.MAX_RETRIEVAL_CANDIDATES
    # Default path chokes single-source-type corpus at MAX_CHUNKS_PER_SOURCE_TYPE.
    assert len(outcome.evidence_pack) <= config.MAX_CHUNKS_PER_SOURCE_TYPE


def test_explicit_query_kind_override_is_honoured() -> None:
    """Callers can pre-classify and pass query_kind explicitly."""
    from backend.core.query_classifier import QueryKindResult

    candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6)
    retriever = _fake_retriever(candidates, corpus_matches=500)
    filters = QueryFilters()

    override = QueryKindResult(kind="survey", signals=["cue:forced"])
    outcome = run_retrieval_plan(
        "What does Section 64 say?",  # factual by default
        filters,
        retriever,
        query_kind=override,
    )

    assert outcome.query_kind is override
    _, kwargs = retriever.retrieve.call_args
    assert kwargs.get("top_k") == config.SURVEY_RETRIEVAL_TOP_K
