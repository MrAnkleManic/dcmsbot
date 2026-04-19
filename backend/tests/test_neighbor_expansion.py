"""Tests for neighbour-chunk expansion in the evidence pack.

After top-N relevance selection, each primary is expanded with its K-1 and K+1
chunks from the same document so synthesis sees sentences that straddle chunk
boundaries. Expansions must stay same-DOC, dedupe against primaries and each
other, and preserve the primary relevance ordering.

Backported from iln_bot@42e0a01.
"""

from typing import Optional

from backend.core.evidence import build_citations, expand_with_neighbors
from backend.core.loader import KnowledgeBase
from backend.core.models import KBChunk


def _make_chunk(
    chunk_id: str,
    doc_id: str,
    text: str,
    prev_chunk_id: Optional[str] = None,
    next_chunk_id: Optional[str] = None,
) -> KBChunk:
    return KBChunk(
        doc_id=doc_id,
        title=f"Document {doc_id}",
        source_type="Act",
        publisher="HMSO",
        date_published="2023-10-26",
        chunk_id=chunk_id,
        chunk_text=text,
        location_pointer=f"{doc_id} chunk {chunk_id}",
        authority_weight=3.0,
        prev_chunk_id=prev_chunk_id,
        next_chunk_id=next_chunk_id,
    )


def _make_kb(*chunks: KBChunk) -> KnowledgeBase:
    kb = KnowledgeBase()
    kb.chunks = list(chunks)
    kb._chunk_index = {c.chunk_id: c for c in chunks}
    return kb


def test_expansion_pulls_prev_and_next_from_same_doc() -> None:
    """A single primary gets its K-1 and K+1 neighbours, both from the same DOC."""
    c1 = _make_chunk("DOC_A::c0", "DOC_A", "first", next_chunk_id="DOC_A::c1")
    c2 = _make_chunk(
        "DOC_A::c1",
        "DOC_A",
        "primary — mid sentence",
        prev_chunk_id="DOC_A::c0",
        next_chunk_id="DOC_A::c2",
    )
    c3 = _make_chunk("DOC_A::c2", "DOC_A", "continuation", prev_chunk_id="DOC_A::c1")
    kb = _make_kb(c1, c2, c3)

    expanded, expansion_ids = expand_with_neighbors([c2], kb)

    assert [c.chunk_id for c in expanded] == ["DOC_A::c0", "DOC_A::c1", "DOC_A::c2"]
    assert expansion_ids == {"DOC_A::c0", "DOC_A::c2"}


def test_no_cross_document_expansion_at_doc_boundary() -> None:
    """First/last chunks of a DOC have null prev/next and must not pull from other DOCs."""
    doc_a_last = _make_chunk("DOC_A::c9", "DOC_A", "last chunk of A", next_chunk_id=None)
    doc_b_first = _make_chunk("DOC_B::c0", "DOC_B", "first chunk of B")
    kb = _make_kb(doc_a_last, doc_b_first)

    expanded, expansion_ids = expand_with_neighbors([doc_a_last], kb)

    assert [c.chunk_id for c in expanded] == ["DOC_A::c9"]
    assert expansion_ids == set()
    # Guard against a regression where a stale next_chunk_id pointed to a
    # different document — expand_with_neighbors must refuse cross-DOC pulls.
    poisoned = _make_chunk(
        "DOC_A::c0",
        "DOC_A",
        "body",
        next_chunk_id="DOC_B::c0",  # deliberately cross-doc
    )
    kb_poisoned = _make_kb(poisoned, doc_b_first)
    expanded_poisoned, expansion_ids_poisoned = expand_with_neighbors([poisoned], kb_poisoned)
    assert [c.chunk_id for c in expanded_poisoned] == ["DOC_A::c0"]
    assert expansion_ids_poisoned == set()


def test_dedup_when_next_of_primary_is_itself_a_primary() -> None:
    """If primary B is the K+1 of primary A, it stays as a primary, not duplicated."""
    c0 = _make_chunk("DOC_A::c0", "DOC_A", "before A", next_chunk_id="DOC_A::c1")
    primary_a = _make_chunk(
        "DOC_A::c1",
        "DOC_A",
        "primary A",
        prev_chunk_id="DOC_A::c0",
        next_chunk_id="DOC_A::c2",
    )
    primary_b = _make_chunk(
        "DOC_A::c2",
        "DOC_A",
        "primary B — also next of A",
        prev_chunk_id="DOC_A::c1",
        next_chunk_id="DOC_A::c3",
    )
    c3 = _make_chunk("DOC_A::c3", "DOC_A", "after B", prev_chunk_id="DOC_A::c2")
    kb = _make_kb(c0, primary_a, primary_b, c3)

    expanded, expansion_ids = expand_with_neighbors([primary_a, primary_b], kb)

    assert [c.chunk_id for c in expanded] == [
        "DOC_A::c0",
        "DOC_A::c1",
        "DOC_A::c2",
        "DOC_A::c3",
    ]
    assert expansion_ids == {"DOC_A::c0", "DOC_A::c3"}
    primary_positions = [
        i for i, c in enumerate(expanded) if c.chunk_id in {"DOC_A::c1", "DOC_A::c2"}
    ]
    assert expanded[primary_positions[0]].chunk_id == "DOC_A::c1"
    assert expanded[primary_positions[1]].chunk_id == "DOC_A::c2"


def test_expansion_preserves_primary_relevance_order() -> None:
    """Primaries stay in the order they were passed; expansions sit adjacent."""
    a_prev = _make_chunk("DOC_A::c4", "DOC_A", "before A", next_chunk_id="DOC_A::c5")
    primary_a = _make_chunk(
        "DOC_A::c5",
        "DOC_A",
        "A body",
        prev_chunk_id="DOC_A::c4",
        next_chunk_id=None,
    )
    primary_b = _make_chunk(
        "DOC_B::c0",
        "DOC_B",
        "B body",
        prev_chunk_id=None,
        next_chunk_id="DOC_B::c1",
    )
    b_next = _make_chunk("DOC_B::c1", "DOC_B", "after B", prev_chunk_id="DOC_B::c0")
    kb = _make_kb(a_prev, primary_a, primary_b, b_next)

    expanded, expansion_ids = expand_with_neighbors([primary_b, primary_a], kb)

    assert [c.chunk_id for c in expanded] == [
        "DOC_B::c0",
        "DOC_B::c1",
        "DOC_A::c4",
        "DOC_A::c5",
    ]
    assert expansion_ids == {"DOC_B::c1", "DOC_A::c4"}


def test_expansion_respects_char_budget() -> None:
    """When the budget is exhausted, primaries are kept but expansions are dropped."""
    primary = _make_chunk(
        "DOC_A::c0",
        "DOC_A",
        "x" * 1000,
        next_chunk_id="DOC_A::c1",
    )
    next_chunk = _make_chunk(
        "DOC_A::c1",
        "DOC_A",
        "y" * 1000,
        prev_chunk_id="DOC_A::c0",
    )
    kb = _make_kb(primary, next_chunk)

    expanded, expansion_ids = expand_with_neighbors([primary], kb, max_chars=1200)

    assert [c.chunk_id for c in expanded] == ["DOC_A::c0"]
    assert expansion_ids == set()


def test_empty_evidence_returns_empty() -> None:
    kb = _make_kb()
    expanded, expansion_ids = expand_with_neighbors([], kb)
    assert expanded == []
    assert expansion_ids == set()


def test_missing_neighbor_in_kb_is_silently_skipped() -> None:
    """A stale next_chunk_id pointing to a vanished chunk must not raise."""
    primary = _make_chunk(
        "DOC_A::c0",
        "DOC_A",
        "body",
        next_chunk_id="DOC_A::c_missing",
    )
    kb = _make_kb(primary)
    expanded, expansion_ids = expand_with_neighbors([primary], kb)
    assert [c.chunk_id for c in expanded] == ["DOC_A::c0"]
    assert expansion_ids == set()


def test_build_citations_marks_expansions() -> None:
    """Citations for expansion chunks carry is_expansion=True; primaries don't."""
    primary = _make_chunk(
        "DOC_A::c0",
        "DOC_A",
        "primary body",
        next_chunk_id="DOC_A::c1",
    )
    expansion = _make_chunk(
        "DOC_A::c1",
        "DOC_A",
        "expansion body",
        prev_chunk_id="DOC_A::c0",
    )
    citations = build_citations(
        [primary, expansion], expansion_ids={"DOC_A::c1"}
    )
    by_chunk = {c.chunk_id: c for c in citations}
    assert by_chunk["DOC_A::c0"].is_expansion is False
    assert by_chunk["DOC_A::c1"].is_expansion is True
    assert {c.citation_id for c in citations} == {"C001", "C002"}
