"""Brief 11 — app.py must classify survey-vs-factual BEFORE the scope
guard so "top N" survey queries don't refuse as UNSUPPORTED_ANALYTICS.

The unit-level guard gating is covered in test_brief11_routing. These
tests pin the app-handler wiring: when the query looks like editorial
curation, the handler passes kind="survey" into classify_query and
proceeds to retrieval; when it looks like quantitative analytics
("how many"), the handler refuses — and that refusal is LEGITIMATE in
DCMS context because BM25 retrieval genuinely cannot answer it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from backend import app as app_module
from backend.core.evidence_sufficiency import EvidenceSignals
from backend.core.models import (
    Answer,
    Confidence,
    KBChunk,
    QueryRequest,
)
from backend.core.query_flow import RetrievalOutcome


def _sample_chunk() -> KBChunk:
    return KBChunk(
        doc_id="OSA_S11",
        title="Online Safety Act 2023 — Section 11",
        source_type="Act",
        publisher="UK Parliament",
        date_published="2023-10-26",
        chunk_id="OSA_S11::c000000",
        chunk_text=(
            "A user-to-user service must take proportionate measures to "
            "mitigate the risks of illegal content appearing on the service."
        ),
        location_pointer="Section 11",
        authority_weight=10.0,
    )


def _supported_answer_fixtures():
    chunk = _sample_chunk()
    from backend.core.retriever import RetrievedChunk

    candidate = RetrievedChunk(
        chunk=chunk, final_score=2.0, bm25_score=2.0, embedding_score=None
    )
    outcome = RetrievalOutcome(
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
    answer = Answer(
        text="A curated selection of main debates on online safety duties.",
        confidence=Confidence(level="medium", reason="Supported by evidence."),
        refused=False,
        refusal_reason=None,
        section_lock="off",
    )
    return chunk, outcome, section_lock, answer


def test_top_n_editorial_curation_bypasses_analytics_refusal():
    """Pre-Brief-11: "Top 5 main debates" was refused by the
    UNSUPPORTED_ANALYTICS guard. Post-fix: the handler pre-classifies as
    survey and lets the query through to retrieval + synthesis."""

    chunk, outcome, section_lock, answer = _supported_answer_fixtures()
    question = "Top 5 main debates on online safety duties during the 2022-23 Parliament."

    with (
        patch.object(app_module, "run_retrieval_plan", return_value=outcome),
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
        patch.object(app_module, "generate_llm_answer", return_value=answer),
        patch.object(
            app_module.retriever,
            "last_context",
            return_value={"section_match": False, "corpus_matches": 80},
        ),
        patch.object(app_module.config, "llm_configured", return_value=True),
        patch.object(app_module, "fetch_parliament_context", return_value={}),
    ):
        response = app_module.query(QueryRequest(question=question))

    assert response.status == "success"
    assert response.answer.refused is False
    # Scope classification should NOT be UNSUPPORTED_ANALYTICS post-Brief-11.
    assert response.scope_classification != "UNSUPPORTED_ANALYTICS"


def test_how_many_times_still_refuses_under_survey_cues():
    """Strict-quantitative analytics ("how many") cannot be answered
    from BM25 retrieval. Even if other survey cues are present in the
    query, the strict patterns win. This refusal is LEGITIMATE for DCMS."""
    question = "How many platforms has Ofcom fined? Tell me everything about it."
    response = app_module.query(QueryRequest(question=question))
    assert response.answer.refused is True
    assert response.scope_classification == "UNSUPPORTED_ANALYTICS"


def test_count_frequency_queries_still_refuse_regardless_of_survey_shape():
    """Even if a user pads a quantitative-analytics question with survey-
    shaped language ("tell me everything about how often …"), the strict
    patterns force UNSUPPORTED_ANALYTICS — they're always-refuse because
    BM25 retrieval genuinely cannot satisfy them."""
    for question in (
        "Tell me everything about how often enforcement notices are issued.",
        "Give me an overview of how many platforms have been fined.",
        "What is the average penalty size? Main debates please.",
    ):
        response = app_module.query(QueryRequest(question=question))
        assert response.answer.refused is True, f"expected refusal for {question!r}"
        assert (
            response.scope_classification == "UNSUPPORTED_ANALYTICS"
        ), f"{question!r} → {response.scope_classification}"
