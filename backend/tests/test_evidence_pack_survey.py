"""PackConfig default + survey widening (Brief 9 sub-job A).

Default pack keeps the pre-Brief-9 factual/precision caps. Survey pack
widens per-doc, per-source-type and char budget so recall-oriented
queries return a fuller evidence pack.
"""

from __future__ import annotations

from backend import config
from backend.core.evidence import PackConfig, build_evidence_pack
from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk


def _candidate(doc_id: str, chunk_id: str, score: float, source_type: str = "Act") -> RetrievedChunk:
    chunk = KBChunk(
        doc_id=doc_id,
        title=f"{doc_id} Act",
        source_type=source_type,
        publisher="UK Parliament",
        date_published="2023-10-26",
        chunk_id=chunk_id,
        chunk_text="Regulated service duties apply to user-to-user services " * 20,
        location_pointer=f"Section {chunk_id}",
        authority_weight=10.0,
    )
    return RetrievedChunk(chunk=chunk, final_score=score, bm25_score=score, embedding_score=None)


def _synthetic_candidates(
    n_docs: int,
    chunks_per_doc: int,
    source_type: str = "Act",
    doc_prefix: str = "DOC",
):
    total = n_docs * chunks_per_doc
    out = []
    for rank in range(total):
        doc_index = rank % n_docs
        chunk_index = rank // n_docs
        doc_id = f"{doc_prefix}_{doc_index:03d}"
        chunk_id = f"{doc_id}::c{chunk_index:03d}"
        score = 1.0 - (rank / total) * 0.5
        out.append(_candidate(doc_id, chunk_id, score, source_type=source_type))
    return out


class TestPackConfigDefaults:
    def test_default_reads_config(self):
        cfg = PackConfig.default()
        assert cfg.max_chunks_to_llm == config.MAX_CHUNKS_TO_LLM
        assert cfg.max_chunks_per_doc == config.MAX_CHUNKS_PER_DOC
        assert cfg.max_chunks_per_source_type == config.MAX_CHUNKS_PER_SOURCE_TYPE
        assert cfg.max_chars_to_llm == config.MAX_CHARS_TO_LLM

    def test_for_survey_reads_survey_config(self):
        cfg = PackConfig.for_survey()
        assert cfg.max_chunks_to_llm == config.SURVEY_MAX_CHUNKS_TO_LLM
        assert cfg.max_chunks_per_doc == config.SURVEY_MAX_CHUNKS_PER_DOC
        assert cfg.max_chunks_per_source_type == config.SURVEY_MAX_CHUNKS_PER_SOURCE_TYPE
        assert cfg.max_chars_to_llm == config.SURVEY_MAX_CHARS_TO_LLM

    def test_survey_is_meaningfully_wider_than_default(self):
        d = PackConfig.default()
        s = PackConfig.for_survey()
        # Survey should at minimum widen per-doc + per-source-type for recall.
        assert s.max_chunks_per_doc >= d.max_chunks_per_doc
        assert s.max_chunks_per_source_type >= d.max_chunks_per_source_type
        assert s.max_chars_to_llm >= d.max_chars_to_llm
        assert s.max_chunks_to_llm >= d.max_chunks_to_llm


class TestBuildEvidencePackDefault:
    """Default pack = pre-Brief-9 behaviour. MAX_CHUNKS_PER_SOURCE_TYPE=5
    caps single-source-type queries; MAX_CHUNKS_PER_DOC=1 forces doc
    diversity."""

    def test_default_caps_single_source_type(self):
        candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6, source_type="Act")
        pack = build_evidence_pack(candidates)
        assert len(pack) <= config.MAX_CHUNKS_PER_SOURCE_TYPE


class TestBuildEvidencePackSurvey:
    """Survey pack widens the caps so recall-oriented queries pull more
    chunks across more documents."""

    def test_survey_widens_pack_beyond_default(self):
        candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6, source_type="Act")
        pack = build_evidence_pack(candidates, pack_config=PackConfig.for_survey())
        # Survey widening should produce more chunks than the default cap.
        assert len(pack) > config.MAX_CHUNKS_PER_SOURCE_TYPE

    def test_survey_honours_per_doc_cap(self):
        cfg = PackConfig.for_survey()
        candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6, source_type="Act")
        pack = build_evidence_pack(candidates, pack_config=cfg)
        doc_counts = {}
        for chunk in pack:
            doc_counts[chunk.doc_id] = doc_counts.get(chunk.doc_id, 0) + 1
        assert max(doc_counts.values()) <= cfg.max_chunks_per_doc

    def test_survey_spans_multiple_docs(self):
        # Acceptance-criterion-ish: a survey pack should pull chunks from
        # multiple documents, not just the top-scoring one.
        candidates = _synthetic_candidates(n_docs=20, chunks_per_doc=6, source_type="Act")
        pack = build_evidence_pack(candidates, pack_config=PackConfig.for_survey())
        distinct_docs = {chunk.doc_id for chunk in pack}
        assert len(distinct_docs) >= 5

    def test_survey_multi_source_type_preserved(self):
        """DCMS-specific: with multiple source types in the candidate pool,
        the per-source-type cap (set conservatively for DCMS) must not
        choke Parliament / Ofcom / debate sources."""
        act_cands = _synthetic_candidates(
            n_docs=15, chunks_per_doc=3, source_type="Act", doc_prefix="ACT"
        )
        ofcom_cands = _synthetic_candidates(
            n_docs=8, chunks_per_doc=3, source_type="Ofcom Guidance", doc_prefix="OFCOM"
        )
        hansard_cands = _synthetic_candidates(
            n_docs=5, chunks_per_doc=2, source_type="Hansard", doc_prefix="HANSARD"
        )
        # Interleave the three streams so scoring is mixed.
        all_cands = []
        for a, o, h in zip(act_cands, ofcom_cands, hansard_cands):
            all_cands.extend([a, o, h])
        all_cands.extend(act_cands[len(hansard_cands):])

        pack = build_evidence_pack(all_cands, pack_config=PackConfig.for_survey())
        source_types_in_pack = {chunk.source_type for chunk in pack}
        # All three source types should survive the per-source-type cap.
        assert "Act" in source_types_in_pack
        assert "Ofcom Guidance" in source_types_in_pack
        assert "Hansard" in source_types_in_pack
