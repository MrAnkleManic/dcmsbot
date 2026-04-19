"""Regression tests for the /refresh embedding-invalidation fix.

Prior to the fix, /refresh reloaded the KB and rebuilt BM25 but kept the
old embedding matrix alive. For a growing corpus this meant:

- new chunks were absent from the embedding matrix, so hybrid/embedding
  retrieval mode either crashed on out-of-range indexing or silently
  returned stale rankings;
- a process restart was required before post-ingest queries could see
  newly-ingested documents.

The fix is twofold:

1. Retriever.build() now invalidates self._embeddings (the corpus may
   have changed out from under it).
2. Retriever.rebuild_embeddings() eagerly regenerates the matrix so the
   /refresh response can confirm the new shape and the first subsequent
   query is not penalised by cold-start embedding generation.

Backported from iln_bot@fe655c3.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.core.loader import KnowledgeBase
from backend.core.models import KBChunk, QueryFilters
from backend.core.retriever import Retriever, _chunk_index_text


_EMBED_DIM = 8


def _signature_vector(text: str) -> list[float]:
    """Deterministic unit-ish vector derived from chunk content.

    Each keyword slot gets its own axis so a query containing "platypus"
    scores highest against the chunk that also contains "platypus".
    """
    vec = [0.0] * _EMBED_DIM
    if "platypus" in text:
        vec[0] = 1.0
    elif "ofcom" in text:
        vec[1] = 1.0
    elif "parliament" in text:
        vec[2] = 1.0
    else:
        vec[3] = 1.0
    return vec


def _stub_build(self: Retriever) -> np.ndarray | None:
    if not self.kb.chunks:
        return None
    texts = [_chunk_index_text(c) for c in self.kb.chunks]
    return np.array([_signature_vector(t) for t in texts], dtype=np.float32)


def _stub_query(self: Retriever, query: str) -> np.ndarray | None:
    return np.array(_signature_vector(query), dtype=np.float32)


def _chunk(chunk_id: str, text: str, header: str | None = None) -> KBChunk:
    return KBChunk(
        doc_id=chunk_id.split("_")[0],
        title="Online Safety Act 2023",
        source_type="Act",
        publisher="HMSO",
        date_published="2023-10-26",
        chunk_id=chunk_id,
        chunk_text=text,
        header=header,
        location_pointer=header or "Section 1",
        authority_weight=3.0,
    )


@pytest.fixture()
def seeded_retriever(monkeypatch: pytest.MonkeyPatch) -> Retriever:
    monkeypatch.setattr(Retriever, "_build_embeddings", _stub_build)
    monkeypatch.setattr(Retriever, "_embed_query", _stub_query)
    monkeypatch.setattr(
        "backend.core.retriever.config.embeddings_configured", lambda: True
    )

    kb = KnowledgeBase()
    kb.chunks = [
        _chunk("A_0001", "Ofcom must publish guidance on illegal-content duties."),
        _chunk("A_0002", "Parliament debated the user-empowerment provisions at length."),
    ]
    retriever = Retriever(kb)
    retriever.build()
    retriever.rebuild_embeddings()
    return retriever


def test_build_invalidates_stale_embedding_matrix(seeded_retriever: Retriever) -> None:
    """The core bug: build() used to leave self._embeddings pointing at the
    previous matrix. After a reload with a different chunk count that matrix
    is misaligned with self.kb.chunks."""
    assert seeded_retriever._embeddings is not None
    assert seeded_retriever._embeddings.shape == (2, _EMBED_DIM)

    seeded_retriever.kb.chunks.append(
        _chunk("B_0001", "A very rare platypus appeared in committee evidence.")
    )
    seeded_retriever.build()

    assert seeded_retriever._embeddings is None, (
        "build() must invalidate the stale matrix; otherwise queries either "
        "crash on out-of-range indexing or return stale rankings until restart."
    )


def test_rebuild_embeddings_reports_new_shape(seeded_retriever: Retriever) -> None:
    seeded_retriever.kb.chunks.append(
        _chunk("B_0001", "A very rare platypus appeared in committee evidence.")
    )
    seeded_retriever.build()
    info = seeded_retriever.rebuild_embeddings()

    assert info["chunk_count"] == 3
    assert info["dim"] == _EMBED_DIM
    assert info["rebuilt_at"]
    assert seeded_retriever._embeddings is not None
    assert seeded_retriever._embeddings.shape == (3, _EMBED_DIM)


def test_query_after_refresh_finds_newly_ingested_chunk(
    seeded_retriever: Retriever,
) -> None:
    """End-to-end regression: simulate an ingest + /refresh cycle and verify
    that content present only in the new chunk surfaces in the top-N."""
    new_chunk = _chunk(
        "B_0001",
        "A very rare platypus was cited in select-committee evidence this week.",
    )
    seeded_retriever.kb.chunks.append(new_chunk)

    seeded_retriever.build()
    seeded_retriever.rebuild_embeddings()

    filters = QueryFilters()
    results = seeded_retriever.retrieve("platypus", filters, top_k=5)
    top_ids = [r.chunk.chunk_id for r in results]
    assert new_chunk.chunk_id in top_ids, (
        f"Expected the platypus query to surface the newly-ingested chunk, "
        f"got {top_ids}. On the pre-fix code this either raised an "
        f"IndexError (hybrid mode) or returned only the pre-refresh chunks."
    )


def test_save_npy_cache_is_atomic(tmp_path: Path, seeded_retriever: Retriever) -> None:
    """The .npy cache write uses a temp file + os.replace so concurrent
    mmap readers never see a partial file. Verify the target ends up at the
    expected path and the temp file is cleaned up on success."""
    target = tmp_path / "embeddings.npy"
    arr = np.arange(12, dtype=np.float32).reshape(3, 4)

    seeded_retriever._save_npy_cache(target, arr)

    assert target.exists()
    loaded = np.load(target)
    np.testing.assert_array_equal(loaded, arr)
    leftover = list(tmp_path.glob("embeddings.npy.tmp*"))
    assert leftover == []


def test_rebuild_embeddings_when_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If embeddings aren't configured (e.g. no OpenAI key), /refresh must
    still succeed and report zero chunks rather than raise."""
    monkeypatch.setattr(
        "backend.core.retriever.config.embeddings_configured", lambda: False
    )

    kb = KnowledgeBase()
    kb.chunks = [_chunk("A_0001", "A single Act provision.")]
    retriever = Retriever(kb)
    retriever.build()
    info = retriever.rebuild_embeddings()

    assert info["chunk_count"] == 0
    assert info["rebuilt_at"]
    assert retriever._embeddings is None
