"""Brief 12 — Porter stemmer on BM25 tokenisation.

Context: Brief 11's survey queries ("were there any fines imposed?",
"any enforcement actions taken?") missed chunks that said "fined" /
"enforced" because BM25 is exact-token. Porter collapses all three
forms ("fines" / "fined" / "fining" → "fine"; "enforcement" / "enforced"
→ "enforc") so stem-based BM25 now recovers them.

Disk-backed caches: DCMS has a committed embeddings_cache.npy plus
runtime .cache/*.npy files (Brief 6 refresh path). Those caches key on
chunk_text + embedding model, NOT on our BM25 tokenisation — swapping
the stemmer does not invalidate them. BM25 itself has no disk cache in
this codebase; the index is rebuilt in memory on every startup. No
cache invalidation hooks are needed.

These tests pin:
1. Porter collapses the key morphological variants the brief called out.
2. Index-time and query-time tokens match stem-to-stem.
3. The _STEMMED_STOPWORDS set agrees with _CORPUS_MATCH_STOPWORDS under
   the same normaliser.
4. A tiny end-to-end BM25 query for "fines" scores a chunk whose text
   says "fined" above a morphologically-unrelated decoy.
"""

from __future__ import annotations

import pytest

from backend.core.retriever import (
    _CORPUS_MATCH_STOPWORDS,
    _STEMMED_STOPWORDS,
    _normalise_token,
    _tokenize,
)


@pytest.fixture
def bm25_only(monkeypatch):
    """Force BM25-only retrieval so embeddings do not mask the stem-based
    matching behaviour the test is asserting on.

    Patches ``backend.config.RETRIEVAL_MODE`` directly rather than the env
    var because ``config`` snapshots the env at import time, so a late
    ``monkeypatch.setenv`` wouldn't reach the Retriever.
    """
    monkeypatch.setattr("backend.config.RETRIEVAL_MODE", "bm25")


# ── Token normalisation ────────────────────────────────────────────────────

class TestStemmedTokenisation:
    def test_fine_family_collapses_to_one_stem(self):
        # DCMS equivalent of the ILN "murder" case: "fined" (Ofcom chunk)
        # vs "fines" (user query) must collide after stemming.
        assert _normalise_token("fines") == "fine"
        assert _normalise_token("fined") == "fine"
        assert _normalise_token("fining") == "fine"
        assert _normalise_token("fine") == "fine"

    def test_enforcement_family_collapses(self):
        # "enforcement" / "enforced" / "enforcing" all stem to "enforc".
        stem = _normalise_token("enforcement")
        assert _normalise_token("enforced") == stem
        assert _normalise_token("enforcing") == stem

    def test_report_family_collapses(self):
        # Brief 11's scaffolding stopword "reported" must stem to the
        # same token as "reports" / "reporting" so the single entry
        # "report" in _STEMMED_STOPWORDS blocks all three forms.
        assert _normalise_token("reported") == "report"
        assert _normalise_token("reporting") == "report"
        assert _normalise_token("reports") == "report"

    def test_numeric_tokens_pass_through(self):
        # Section numbers and years must not be mangled. "2023" and "64"
        # are common DCMS scaffolding but must survive tokenisation
        # unchanged so the numeric filter in _extract_content_tokens
        # still recognises them.
        assert _normalise_token("2023") == "2023"
        assert _normalise_token("64") == "64"
        assert _tokenize("2023")[0] == "2023"

    def test_possessive_suffix_stripped_before_stemming(self):
        # Porter is undefined on tokens with embedded apostrophes, so
        # we strip "'s" / trailing "'" first.
        assert _normalise_token("ofcom's") == "ofcom"
        assert _normalise_token("government's") == _normalise_token("government")

    def test_empty_token_safe(self):
        # A bare "'s" (which _TOKEN_PATTERN can match) must not crash.
        assert _normalise_token("'s") == ""
        assert _tokenize("'s") == []

    def test_tokenize_consistent_between_query_and_index(self):
        # The whole point: tokens produced by _tokenize from a query and
        # from a chunk must share stems so BM25 can match across them.
        chunk_like = "Ofcom fined the search service provider under Section 10"
        query_like = "what fines are imposed on search services"
        chunk_tokens = set(_tokenize(chunk_like))
        query_tokens = set(_tokenize(query_like))
        # "fine" stem in both ("fined"→"fine" in chunk; "fines"→"fine" in query).
        assert "fine" in chunk_tokens
        assert "fine" in query_tokens
        # "search" stays bare in both.
        assert "search" in chunk_tokens
        assert "search" in query_tokens
        # "services"/"service" both stem to "servic".
        assert _normalise_token("service") == _normalise_token("services")


# ── Stopword parity ────────────────────────────────────────────────────────

class TestStemmedStopwords:
    def test_every_raw_stopword_has_a_stem_entry(self):
        # If we add a word to _CORPUS_MATCH_STOPWORDS but forget to
        # rebuild the stemmed set, the stopword quietly stops working.
        # This test pins the invariant.
        for raw in _CORPUS_MATCH_STOPWORDS:
            stemmed = _normalise_token(raw)
            if stemmed:
                assert stemmed in _STEMMED_STOPWORDS, (
                    f"Stopword {raw!r} stems to {stemmed!r} which is not "
                    f"in _STEMMED_STOPWORDS"
                )

    def test_reported_family_filtered_after_stemming(self):
        # Surface forms "reported" / "reporting" / "reports" all vanish
        # from the content-token stream because they stem to "report"
        # which is in _STEMMED_STOPWORDS.
        for surface in ("reported", "reporting", "reports"):
            assert _normalise_token(surface) in _STEMMED_STOPWORDS

    def test_topic_words_not_accidentally_stopworded(self):
        # Regression guard: DCMS topic anchors (Ofcom, online, safety,
        # regulator, enforcement, etc.) must NOT leak into the stopword
        # set via an over-stemmed scaffolding word — that would silently
        # kill corpus_matches for those queries.
        for topic in ("ofcom", "online", "safety", "regulator", "enforc",
                      "platform", "hansard"):
            assert topic not in _STEMMED_STOPWORDS


# ── End-to-end BM25 ranking ────────────────────────────────────────────────

class TestBM25FinesQueryRecoversFinedChunk:
    """Smoke test that the stemmed BM25 surfaces a chunk saying "fined"
    when the query says "fines" — the exact bug the brief targets."""

    @staticmethod
    def _chunk(doc_id: str, chunk_id: str, text: str):
        from backend.core.models import KBChunk
        return KBChunk(
            doc_id=doc_id,
            chunk_id=chunk_id,
            chunk_text=text,
            title="t",
            source_type="Ofcom Guidance",
            publisher="Ofcom",
            date_published="2023-10-26",
        )

    def test_fines_query_surfaces_fined_chunk(self, bm25_only):
        from backend.core.loader import KnowledgeBase
        from backend.core.models import QueryFilters
        from backend.core.retriever import Retriever

        kb = KnowledgeBase()
        kb.chunks = [
            # Target: past-tense "fined" — pre-Brief-12 invisible to
            # a "fines" query.
            self._chunk(
                "DOC_A",
                "c1",
                "Ofcom fined the service provider £500,000 for breach of duty.",
            ),
            # Decoy: unrelated topic, deliberately shares no stemmed
            # tokens with the query.
            self._chunk(
                "DOC_B",
                "c2",
                "Shipping activity at Liverpool harbour was brisk all spring.",
            ),
            self._chunk(
                "DOC_C",
                "c3",
                "The weather last April turned unseasonably warm.",
            ),
        ]
        retriever = Retriever(kb)
        retriever.build()

        results = retriever.retrieve(
            "Were there any fines imposed under the Online Safety Act?",
            QueryFilters(),
            top_k=3,
        )
        assert results, "Expected at least one hit after stemming"

        # The target chunk ("fined") should rank top under stemmed BM25 —
        # it's the only chunk containing the "fine" stem. Pre-Brief-12
        # BM25 would have scored it 0 on that token.
        top = results[0]
        assert top.chunk.chunk_id == "c1", (
            f"Expected fined-chunk on top, got {top.chunk.chunk_id}"
        )
        assert top.bm25_score > 0

    def test_stemmed_bm25_scores_past_tense_chunk_nonzero(self, bm25_only):
        """Minimum bar: the query 'fines' must produce a non-zero BM25
        score against a chunk that only says 'fined'. Pre-Brief-12
        this score was exactly 0 and the case was invisible."""
        from backend.core.loader import KnowledgeBase
        from backend.core.models import QueryFilters
        from backend.core.retriever import Retriever

        kb = KnowledgeBase()
        kb.chunks = [
            self._chunk(
                "DOC_A",
                "c1",
                "The provider was fined for failing to meet the Section 11 duty.",
            ),
            # Three unrelated decoys so BM25's IDF math is stable — on a
            # single-chunk corpus BM25Okapi can return negative scores.
            self._chunk("DOC_B", "c2", "Shipping news from Liverpool harbour."),
            self._chunk("DOC_C", "c3", "Fashion plate for the spring season."),
            self._chunk("DOC_D", "c4", "Flower show in Hyde Park."),
        ]
        retriever = Retriever(kb)
        retriever.build()
        # Query uses the plural noun form, which pre-Brief-12 would never
        # have hit the "fined" chunk.
        results = retriever.retrieve("fines", QueryFilters(), top_k=4)
        assert results
        top = results[0]
        assert top.chunk.chunk_id == "c1"
        assert top.bm25_score > 0, (
            f"Stemmed BM25 must give a positive score when the query "
            f"uses 'fines' and the only matching chunk says 'fined'. "
            f"Got {top.bm25_score}."
        )
