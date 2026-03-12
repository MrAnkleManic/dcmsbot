import pytest

from backend.core.loader import KnowledgeBase
from backend.core.models import KBChunk, QueryFilters
from backend.core.retriever import (
    Retriever,
    chunk_belongs_to_section,
    extract_section_ref,
)


def _chunk(
    chunk_id: str,
    text: str,
    header: str,
    source_type: str = "Act of Parliament",
    authority: float = 10.0,
) -> KBChunk:
    return KBChunk(
        doc_id=chunk_id.split("_")[0],
        title="Online Safety Act",
        source_type=source_type,
        publisher="Parliament",
        date_published="2023",
        chunk_id=chunk_id,
        chunk_text=text,
        header=header,
        location_pointer=header,
        authority_weight=authority,
    )


@pytest.fixture()
def retriever() -> Retriever:
    kb = KnowledgeBase()
    section_64_text = (
        "Section heading: Section 64 User identity verification\n"
        "(1) A provider of a Category 1 service must offer all adult users of the service "
        "the option to verify their identity."
    )
    kb.chunks = [
        _chunk("ACT_064", section_64_text, "Section 64 User identity verification"),
        _chunk("ACT_DUP", section_64_text, "Section 64 User identity verification"),  # duplicate text
        _chunk(
            "ACT_010",
            "Section heading: Section 10 Illegal content\nProviders must manage illegal content risks.",
            "Section 10 Illegal content",
        ),
        _chunk(
            "NOTES_064",
            "Clause 64: transparency reports and explanatory material",
            "Clause 64 transparency reports",
            source_type="Explanatory Notes",
            authority=6.0,
        ),
    ]
    retriever = Retriever(kb)
    retriever.build()
    return retriever


def test_section_first_and_primary_filter(retriever: Retriever) -> None:
    filters = QueryFilters(primary_only=True, include_guidance=False, include_debates=False)

    results = retriever.retrieve("What does section 64 require?", filters, top_k=5)
    assert results, "Expected retrieval results for section query"

    top_chunk = results[0].chunk
    assert "Section 64" in (top_chunk.header or top_chunk.chunk_text)
    assert top_chunk.source_type == "Act of Parliament"

    assert all(r.chunk.source_type == "Act of Parliament" for r in results)

    # ensure deduplication removed duplicate section chunks
    normalized_texts = {" ".join(r.chunk.chunk_text.split()).lower() for r in results}
    assert len(normalized_texts) == len(results)

    context = retriever.last_context()
    assert context["section_match"] is True
    assert context["section_value"] == 64


def test_chunk_matches_section_text_matching() -> None:
    chunk_65 = _chunk(
        "ACT_065",
        "Section 65 OFCOM’s guidance about user identity verification",
        "Section heading: Section 65 OFCOM’s guidance about user identity verification",
    )
    chunk_64 = _chunk(
        "ACT_064",
        "Section 64 User identity verification",
        "Section heading: Section 64 User identity verification",
    )
    empty_chunk = _chunk(
        "ACT_EMPTY",
        "",
        "",
    )

    cross_reference = "See section 65 for related duties."

    assert chunk_belongs_to_section(f"{chunk_65.header}\n{chunk_65.chunk_text}", 65) is True
    assert chunk_belongs_to_section(f"{chunk_64.header}\n{chunk_64.chunk_text}", "65") is False
    assert chunk_belongs_to_section(cross_reference, "65") is False
    assert chunk_belongs_to_section(f"{empty_chunk.header}\n{empty_chunk.chunk_text}", "65") is False


def test_extract_section_ref_variants() -> None:
    assert extract_section_ref("What does section 65 require?") == {
        "kind": "section",
        "value": "65",
        "subsection": None,
        "raw": "section 65",
    }
    assert extract_section_ref("What does s.65 cover?") == {
        "kind": "section",
        "value": "65",
        "subsection": None,
        "raw": "s.65",
    }
    assert extract_section_ref("Explain § 65 remedies") == {
        "kind": "section",
        "value": "65",
        "subsection": None,
        "raw": "§ 65",
    }
    assert extract_section_ref("Details of Section 65(1)") == {
        "kind": "section",
        "value": "65",
        "subsection": "(1)",
        "raw": "Section 65(1)",
    }


def test_section_locked_retrieval_excludes_cross_references(retriever: Retriever) -> None:
    filters = QueryFilters(primary_only=True, include_guidance=False, include_debates=False)
    cross_ref_chunk = _chunk(
        "ACT_REF",
        "General guidance",
        "Providers must comply with this Act in accordance with section 65 and section 64 duties.",
    )
    retriever.kb.chunks.append(cross_ref_chunk)
    retriever.build()

    results = retriever.retrieve("What does section 64 require?", filters, top_k=5)
    assert results, "Expected results for section retrieval"
    assert all(
        chunk_belongs_to_section(f"{r.chunk.header}\n{r.chunk.chunk_text}", "64") for r in results
    )
    assert all("ACT_REF" != r.chunk.chunk_id for r in results)


def test_guidance_filter_accepts_legacy_policy_docs_type() -> None:
    kb = KnowledgeBase()
    guidance_chunk = KBChunk(
        doc_id="GUIDE_001",
        title="Ofcom safety guidance",
        source_type="Policy Docs & Guidance",
        publisher="Ofcom",
        date_published="2023",
        chunk_id="GUIDE_001_0001",
        chunk_text="Guidance text content",
        header=None,
        location_pointer="page 1",
        authority_weight=1.0,
    )
    act_chunk = KBChunk(
        doc_id="ACT_001",
        title="Online Safety Act",
        source_type="Act",
        publisher="Parliament",
        date_published="2023",
        chunk_id="ACT_001_0001",
        chunk_text="Act content",
        header=None,
        location_pointer="page 2",
        authority_weight=10.0,
    )
    kb.chunks = [guidance_chunk, act_chunk]
    retriever = Retriever(kb)

    filters = QueryFilters(primary_only=False, include_guidance=True, include_debates=False)
    filtered, _ = retriever._filter_chunks(filters)
    assert guidance_chunk in filtered

    filters_no_guidance = QueryFilters(
        primary_only=False, include_guidance=False, include_debates=False
    )
    filtered_no_guidance, _ = retriever._filter_chunks(filters_no_guidance)
    assert guidance_chunk not in filtered_no_guidance
