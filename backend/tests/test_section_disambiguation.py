import pytest

from backend.core.evidence import build_citations, build_evidence_pack, generate_answer
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


@pytest.fixture()
def section_retrieval_context() -> dict:
    kb = KnowledgeBase()
    section_64_text = (
        "Section heading: Section 64 User identity verification\n"
        "A provider of a Category 1 service must offer all adult users the option to verify their identity. "
        "Providers must also consider related obligations; see section 65(1) for guidance duties."
    )
    section_65_text = (
        "Section heading: Section 65 Guidance about identity verification\n"
        "OFCOM must produce guidance about user identity verification under section 64(1). "
        "Before publishing that guidance, OFCOM must consult the Information Commissioner."
    )
    chunk_64 = _chunk("OSA_064", "Section 64 User identity verification", section_64_text)
    chunk_65 = _chunk("OSA_065", "Section 65 Guidance about identity verification", section_65_text)

    kb.chunks = [chunk_64, chunk_65]
    retriever = Retriever(kb)
    retriever.build()
    filters = QueryFilters(primary_only=True, include_guidance=False, include_debates=False)
    return {"retriever": retriever, "filters": filters, "chunk_64": chunk_64, "chunk_65": chunk_65}


def _answer_question(context: dict, question: str):
    candidates = context["retriever"].retrieve(question, context["filters"], top_k=5)
    evidence = build_evidence_pack(candidates)
    citations = build_citations(evidence)
    answer = generate_answer(question, evidence, citations)
    return answer, citations, evidence


def test_section_64_answer_uses_matching_chunk(section_retrieval_context: dict) -> None:
    answer, citations, evidence = _answer_question(
        section_retrieval_context, "What does section 64 require?"
    )

    assert citations[0].chunk_id == section_retrieval_context["chunk_64"].chunk_id
    assert evidence[0].chunk_id == section_retrieval_context["chunk_64"].chunk_id
    assert "offer all adult users the option to verify their identity" in answer.text.lower()


def test_section_65_answer_stays_on_section(section_retrieval_context: dict) -> None:
    answer, citations, evidence = _answer_question(
        section_retrieval_context, "What does section 65 require?"
    )

    assert citations[0].chunk_id == section_retrieval_context["chunk_65"].chunk_id
    assert evidence[0].chunk_id == section_retrieval_context["chunk_65"].chunk_id
    lower_answer = answer.text.lower()
    assert "ofcom must produce guidance" in lower_answer
    assert "consult the information commissioner" in lower_answer


def test_missing_section_adds_warning(section_retrieval_context: dict) -> None:
    answer, citations, evidence = _answer_question(
        section_retrieval_context, "What does section 99 require?"
    )

    assert citations
    assert evidence
    assert "warning: exact section match not found in retrieved evidence." in answer.text.lower()
    assert answer.confidence.level == "low"
