from types import SimpleNamespace
from datetime import datetime
from unittest.mock import patch

from backend import app as app_module
from fastapi import HTTPException
from backend.core.evidence_sufficiency import EvidenceSignals
from backend.core.models import (
    Answer,
    Confidence,
    KBChunk,
    KBStatus,
    QueryRequest,
)
from backend.core.query_flow import RetrievalOutcome
from backend.core.query_guard import QueryClassification
from backend.core.retriever import RetrievedChunk


def _sample_chunk() -> KBChunk:
    return KBChunk(
        doc_id="DOC_001",
        title="Online Safety Act 2023",
        source_type="Act of Parliament",
        publisher="Parliament",
        date_published="2023-10-26",
        chunk_id="DOC_001_0001",
        chunk_text="Section 1 sets out the key duties.",
        location_pointer="Section 1",
        authority_weight=10.0,
    )


def test_query_llm_path_preserves_citations_for_supported_answers() -> None:
    chunk = _sample_chunk()
    candidate = RetrievedChunk(
        chunk=chunk,
        final_score=2.0,
        bm25_score=2.0,
        embedding_score=None,
    )
    retrieval_outcome = RetrievalOutcome(
        candidates=[candidate],
        evidence_pack=[chunk],
        top_score=2.0,
        definition_mode=False,
        used_definition_candidates=False,
        definition_candidates=None,
    )
    section_lock = SimpleNamespace(
        active=False,
        filtered_candidates=[candidate],
        has_matches=False,
        section_number=None,
        label="off",
    )
    llm_answer = Answer(
        text="Supported answer.",
        confidence=Confidence(level="medium", reason="Supported by evidence."),
        refused=False,
        refusal_reason=None,
        section_lock="off",
    )

    with (
        patch.object(app_module, "classify_query", return_value=QueryClassification.IN_SCOPE),
        patch.object(app_module, "run_retrieval_plan", return_value=retrieval_outcome),
        patch.object(app_module, "apply_section_lock", return_value=section_lock),
        patch.object(
            app_module,
            "assess_evidence_sufficiency",
            return_value=EvidenceSignals(
                status="ok",
                top_score=2.0,
                coverage=1.0,
                separation=2.0,
                confidence_label="high",
            ),
        ),
        patch.object(app_module, "should_refuse", return_value=False),
        patch.object(app_module, "generate_llm_answer", return_value=llm_answer),
        patch.object(app_module.retriever, "last_context", return_value={"section_match": False}),
        patch.object(app_module.config, "llm_configured", return_value=True),
    ):
        response = app_module.query(QueryRequest(question="What does section 1 require?"))

    assert response.answer.refused is False
    assert response.status == "success"
    assert len(response.citations) == 1
    assert response.citations[0].chunk_id == chunk.chunk_id


def test_query_falls_back_when_llm_errors() -> None:
    chunk = _sample_chunk()
    candidate = RetrievedChunk(
        chunk=chunk,
        final_score=2.0,
        bm25_score=2.0,
        embedding_score=None,
    )
    retrieval_outcome = RetrievalOutcome(
        candidates=[candidate],
        evidence_pack=[chunk],
        top_score=2.0,
        definition_mode=False,
        used_definition_candidates=False,
        definition_candidates=None,
    )
    section_lock = SimpleNamespace(
        active=False,
        filtered_candidates=[candidate],
        has_matches=False,
        section_number=None,
        label="off",
    )
    llm_error_answer = Answer(
        text="LLM synthesis encountered an error. Falling back to evidence excerpts.",
        confidence=Confidence(level="low", reason="LLM call failed."),
        refused=True,
        refusal_reason="LLM synthesis error.",
        section_lock="off",
    )

    with (
        patch.object(app_module, "classify_query", return_value=QueryClassification.IN_SCOPE),
        patch.object(app_module, "run_retrieval_plan", return_value=retrieval_outcome),
        patch.object(app_module, "apply_section_lock", return_value=section_lock),
        patch.object(
            app_module,
            "assess_evidence_sufficiency",
            return_value=EvidenceSignals(
                status="ok",
                top_score=2.0,
                coverage=1.0,
                separation=2.0,
                confidence_label="high",
            ),
        ),
        patch.object(app_module, "should_refuse", return_value=False),
        patch.object(app_module, "generate_llm_answer", return_value=llm_error_answer),
        patch.object(app_module.retriever, "last_context", return_value={"section_match": False}),
        patch.object(app_module.config, "llm_configured", return_value=True),
    ):
        response = app_module.query(QueryRequest(question="What does section 1 require?"))

    assert response.answer.refused is False
    assert response.status == "success"
    assert len(response.citations) == 1
    assert response.citations[0].chunk_id == chunk.chunk_id


def test_kb_stats_returns_counts_expected_by_frontend() -> None:
    kb_status = KBStatus(
        last_refreshed="2026-02-09T10:03:34.130000",
        kb_loaded=True,
        total_chunks=28548,
        doc_counts_by_type={"Act": 1000, "Regulator Guidance": 200},
        doc_counts_by_raw_type={},
        chunk_counts_by_type={"Act": 12000, "Regulator Guidance": 7000},
        guidance_source_counts={},
        validation_errors=[],
        config_limits={},
        ingestion_summary={},
    )

    with patch.object(app_module.loader.kb, "status", return_value=kb_status):
        response = app_module.kb_stats()

    assert response["total_chunks"] == 28548
    assert response["doc_counts_by_type"] == {"Act": 1000, "Regulator Guidance": 200}
    assert response["chunk_counts_by_type"] == {"Act": 12000, "Regulator Guidance": 7000}
    assert response["categories"] == response["chunk_counts_by_type"]
    assert response["last_refreshed"] == "2026-02-09T10:03:34.130000"


def test_api_alias_routes_are_registered() -> None:
    route_methods = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in app_module.app.routes
    }

    assert ("/api/query", ("POST",)) in route_methods
    assert ("/api/status", ("GET",)) in route_methods
    assert ("/api/refresh", ("POST",)) in route_methods
    assert ("/api/debug/retrieve", ("POST",)) in route_methods
    assert ("/api/kb-stats", ("GET",)) in route_methods
    assert ("/api/healthz", ("GET",)) in route_methods
    assert ("/api/readyz", ("GET",)) in route_methods


def test_healthz_returns_ok() -> None:
    response = app_module.healthz()
    assert response["status"] == "ok"
    assert response["version"]


def test_readyz_returns_ready_when_index_and_kb_loaded() -> None:
    with (
        patch.object(app_module.loader.kb, "last_refreshed", datetime.utcnow()),
        patch.object(app_module.retriever, "index_ready", True),
    ):
        response = app_module.readyz()

    assert response["status"] == "ready"
    assert response["kb_loaded"] is True
    assert response["index_ready"] is True


def test_readyz_returns_503_when_not_ready() -> None:
    with (
        patch.object(app_module.loader.kb, "last_refreshed", None),
        patch.object(app_module.retriever, "index_ready", False),
    ):
        try:
            app_module.readyz()
            raised = False
        except HTTPException as exc:
            raised = True
            assert exc.status_code == 503
            assert exc.detail["status"] == "not_ready"
            assert exc.detail["kb_loaded"] is False
            assert exc.detail["index_ready"] is False

    assert raised is True
