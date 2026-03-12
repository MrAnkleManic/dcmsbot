from backend.core.loader import KnowledgeBase
from backend.core.models import KBChunk, QueryFilters
from backend.core.query_flow import run_retrieval_plan
from backend.core.query_guard import QueryClassification, classify_query
from backend.core.retriever import Retriever


def _chunk(chunk_id: str, source_type: str, text: str) -> KBChunk:
    return KBChunk(
        doc_id="OSA",
        title="Online Safety Act",
        source_type=source_type,
        publisher="Parliament",
        date_published="2023",
        chunk_id=chunk_id,
        chunk_text=text,
        header="Section 2 Interpretation",
        location_pointer="s.2",
        authority_weight=10.0 if source_type.lower().startswith("act") else 5.0,
    )


def test_classifies_out_of_scope_and_analytics() -> None:
    assert classify_query("Who is the prime minister right now?") == QueryClassification.OUT_OF_SCOPE
    assert classify_query("How many times did Ofcom publish guidance?") == QueryClassification.UNSUPPORTED_ANALYTICS
    assert classify_query("What is a user-to-user service?") == QueryClassification.IN_SCOPE


def test_definition_plan_prefers_primary_sources() -> None:
    kb = KnowledgeBase()
    act_chunk = _chunk(
        "OSA_DEF",
        "Act of Parliament",
        "User-to-user service is defined as a regulated service that allows online interaction.",
    )
    guidance_chunk = _chunk(
        "GUIDE_DEF",
        "Regulator Guidance",
        "Guidance about user-to-user services.",
    )
    kb.chunks = [guidance_chunk, act_chunk]
    retriever = Retriever(kb)
    retriever.build()

    filters = QueryFilters(primary_only=False, include_guidance=True, include_debates=False)
    outcome = run_retrieval_plan("Where is user-to-user service defined?", filters, retriever)

    assert outcome.definition_mode is True
    assert outcome.used_definition_candidates is True
    assert all(candidate.chunk.source_type.lower().startswith("act") for candidate in outcome.candidates)


def test_definition_plan_falls_back_when_no_primary_definition() -> None:
    kb = KnowledgeBase()
    guidance_chunk = _chunk(
        "GUIDE_DEF",
        "Regulator Guidance",
        "Guidance about user identity verification processes.",
    )
    kb.chunks = [guidance_chunk]
    retriever = Retriever(kb)
    retriever.build()

    filters = QueryFilters(primary_only=False, include_guidance=True, include_debates=False)
    outcome = run_retrieval_plan("Where is identity verification defined?", filters, retriever)

    assert outcome.definition_mode is True
    assert outcome.used_definition_candidates is False
    assert guidance_chunk.chunk_id in {candidate.chunk.chunk_id for candidate in outcome.candidates}
