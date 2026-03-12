from backend.core.evidence import build_evidence_pack
from backend.core.guardrails import (
    apply_section_lock,
    detect_definition_target,
    find_definition_snippet,
)
from backend.core.loader import KnowledgeBase
from backend.core.models import KBChunk, QueryFilters
from backend.core.retriever import Retriever


def _chunk(chunk_id: str, header: str, text: str) -> KBChunk:
    return KBChunk(
        doc_id="OSA",
        title="Online Safety Act",
        source_type="Act of Parliament",
        publisher="Parliament",
        date_published="2023",
        chunk_id=chunk_id,
        chunk_text=text,
        header=header,
        location_pointer=header,
        authority_weight=10.0,
    )


def test_section_lock_filters_to_matching_section() -> None:
    kb = KnowledgeBase()
    chunk_64 = _chunk(
        "OSA_064",
        "Section 64 User identity verification",
        "Section heading: Section 64 User identity verification\nProviders must offer adult users identity checks.",
    )
    chunk_65 = _chunk(
        "OSA_065",
        "Section 65 OFCOM’s guidance about user identity verification",
        "Section heading: Section 65 OFCOM’s guidance about user identity verification\nOFCOM must produce guidance for providers.",
    )
    kb.chunks = [chunk_64, chunk_65]
    retriever = Retriever(kb)
    retriever.build()

    filters = QueryFilters(primary_only=True, include_guidance=False, include_debates=False)
    candidates = retriever.retrieve("What does s.65 require?", filters, top_k=5)

    outcome = apply_section_lock("What does s.65 require?", candidates)
    assert outcome.active is True
    assert outcome.label == "s.65"
    assert outcome.has_matches is True
    assert len(outcome.filtered_candidates) == 1
    assert outcome.filtered_candidates[0].chunk.chunk_id == chunk_65.chunk_id

    evidence = build_evidence_pack(outcome.filtered_candidates)
    assert all("Section 65" in (chunk.header or "") for chunk in evidence)


def test_section_lock_signals_missing_section() -> None:
    kb = KnowledgeBase()
    chunk_64 = _chunk(
        "OSA_064",
        "Section 64 User identity verification",
        "Section heading: Section 64 User identity verification\nProviders must offer adult users identity checks.",
    )
    kb.chunks = [chunk_64]
    retriever = Retriever(kb)
    retriever.build()

    filters = QueryFilters(primary_only=True, include_guidance=False, include_debates=False)
    candidates = retriever.retrieve("Explain section 65 requirements", filters, top_k=5)
    outcome = apply_section_lock("Explain section 65 requirements", candidates)

    assert outcome.active is True
    assert outcome.label == "s.65"
    assert outcome.has_matches is False
    assert outcome.filtered_candidates == candidates
    assert outcome.original_candidates == candidates


def test_definition_detection_requires_explicit_phrase() -> None:
    chunk = _chunk(
        "OSA_DEF",
        "Section 10 Interpretation",
        "\"Adult user\" means an individual aged 18 or over using the service.",
    )
    snippet = find_definition_snippet("adult user", [chunk])
    assert snippet is not None
    extracted, _ = snippet
    assert "means" in extracted.lower()


def test_definition_target_parsing() -> None:
    assert detect_definition_target("Define 'adult user' in section 64") == "adult user"
    assert detect_definition_target("What does safety duty mean?") == "safety duty"
    assert detect_definition_target("Give guidance about section 65") is None
