from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk, _stable_sort_retrieved


def _chunk(doc_id: str, chunk_id: str, text: str) -> KBChunk:
    return KBChunk(
        doc_id=doc_id,
        title="Test Doc",
        source_type="Act of Parliament",
        publisher="Parliament",
        date_published="2023-01-01",
        chunk_id=chunk_id,
        chunk_text=text,
        header="Section 1 Test",
        location_pointer="page 1",
        authority_weight=10.0,
    )


def test_ordering_is_stable_when_scores_tie() -> None:
    chunk_a = _chunk("DOC_A", "DOC_A_0001", "Example text A.")
    chunk_b = _chunk("DOC_B", "DOC_B_0001", "Example text B.")

    cand_a = RetrievedChunk(chunk=chunk_a, final_score=0.5, bm25_score=1.0)
    cand_b = RetrievedChunk(chunk=chunk_b, final_score=0.5, bm25_score=1.0)

    ordered = _stable_sort_retrieved([cand_b, cand_a])
    assert ordered[0].chunk.doc_id == "DOC_A"
    assert ordered[1].chunk.doc_id == "DOC_B"
