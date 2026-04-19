import uuid
from dataclasses import asdict
from collections import Counter
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from backend import config
from backend.core.doc_types import canonical_doc_type
from backend.core import loader
from backend.core.evidence import (
    build_citations,
    build_evidence_pack,
    build_parliament_citations,
    compute_source_freshness,
    enforce_response_consistency,
    format_parliament_evidence_context,
    generate_answer,
    generate_llm_answer,
    log_usage,
    should_refuse,
)
from backend.core.evidence_sufficiency import (
    assess_evidence_sufficiency,
    assess_parliament_evidence,
    contextual_suggestions,
    default_suggestions,
)
from backend.core.guardrails import apply_section_lock
from backend.core.parliament_fetch import fetch_parliament_context
from backend.core.query_flow import run_retrieval_plan
from backend.core.query_guard import (
    QueryClassification,
    classify_query,
    is_in_scope,
    needs_parliament_data,
    needs_strategic_synthesis,
)
from backend.core.query_rewriter import rewrite_follow_up
from backend.core.models import (
    Answer,
    Confidence,
    DebugRetrieveResponse,
    EvidenceAssessment,
    QueryRequest,
    QueryResponse,
    RetrievedChunkDebug,
    RetrievalDebug,
    RetrievalDebugEntry,
    RetrievalDebugSummary,
)
from backend.core.retriever import Retriever, chunk_belongs_to_section, _section_match_text
from backend.logging_config import get_logger
from backend.version import __version__

app = FastAPI(title="DCMS Online Safety Evidence Bot", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_allow_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger = get_logger(__name__)
FRONTEND_DIST_DIR = Path(__file__).resolve().parent.parent / "frontend-v2" / "dist"

retriever = Retriever(loader.kb)


def _debug_excerpt(text: str, max_words: int = config.MAX_EXCERPT_WORDS) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."


def _status_payload() -> dict:
    kb_status = loader.kb.status().dict()
    return {
        **kb_status,
        **retriever.status(),
        "llm_configured": config.llm_configured(),
        "embeddings_configured": config.embeddings_configured(),
        "retrieval_mode": retriever.effective_mode(),
        "version": __version__,
    }


def _build_retrieval_debug(
    candidates, filters, section_lock, definition_mode: bool = False, definition_route_used: bool = False
) -> RetrievalDebug:
    doc_type_counter = Counter()
    safe_candidates = candidates or []
    section_filtered_candidates = (
        section_lock.filtered_candidates or []
        if section_lock and section_lock.active and section_lock.has_matches
        else []
    )
    section_matched_ids = {c.chunk.chunk_id for c in section_filtered_candidates}
    results: list[RetrievalDebugEntry] = []

    for idx, cand in enumerate(safe_candidates[: config.DEBUG_CANDIDATES_LIMIT], start=1):
        chunk = cand.chunk
        doc_type = canonical_doc_type(chunk.source_type)
        doc_type_counter[doc_type] += 1
        flags: list[str] = []
        if section_matched_ids and chunk.chunk_id in section_matched_ids:
            flags.append("SECTION_MATCH")
        if filters.enabled_categories is not None:
            if doc_type in filters.enabled_categories:
                flags.append(f"FILTER_CATEGORY:{doc_type}")
        else:
            if filters.primary_only:
                flags.append("FILTER_PRIMARY_ONLY")
            if filters.include_guidance and doc_type == "Regulator Guidance":
                flags.append("FILTER_INCLUDED:guidance")
            if filters.include_debates and doc_type == "Debates / Hansard":
                flags.append("FILTER_INCLUDED:debates")
        if chunk.authority_weight > 1.0:
            flags.append("BOOSTED_PRIMARY")
        if chunk.reliability_flags:
            flags.extend(chunk.reliability_flags)

        results.append(
            RetrievalDebugEntry(
                rank=idx,
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                doc_type=doc_type,
                raw_doc_type=chunk.source_type,
                title=chunk.title,
                date=chunk.date_published,
                section=chunk.header or chunk.location_pointer,
                location_pointer=chunk.location_pointer,
                relevance_score=cand.final_score,
                bm25_score=cand.bm25_score,
                embedding_score=cand.embedding_score,
                reason_flags=flags,
            )
        )

    summary = RetrievalDebugSummary(
        filters=filters.dict(),
        section_lock=section_lock.label if section_lock else "off",
        retrieval_mode=retriever.effective_mode(),
        doc_type_breakdown=dict(doc_type_counter),
        definition_mode=definition_mode,
        definition_route_used=definition_route_used,
    )
    return RetrievalDebug(summary=summary, results=results)


@app.on_event("startup")
def startup_event() -> None:
    loader.kb.load(config.KB_DIR)
    retriever.build()


def _active_categories_for_filters(filters: "QueryFilters", all_categories: list[str]) -> list[str]:
    """Given the current filter state, return which canonical doc-type categories are active."""
    if filters.enabled_categories is not None:
        enabled_lower = {c.lower() for c in filters.enabled_categories}
        return [cat for cat in all_categories if cat.lower() in enabled_lower]
    active = []
    for cat in all_categories:
        if filters.primary_only and cat != "Act":
            continue
        if not filters.include_guidance and cat == "Regulator Guidance":
            continue
        if not filters.include_debates and cat == "Debates / Hansard":
            continue
        active.append(cat)
    return active


@app.post("/query", response_model=QueryResponse)
@app.post("/api/query", response_model=QueryResponse, include_in_schema=False)
def query(req: QueryRequest) -> QueryResponse:
    query_id = str(uuid.uuid4())
    logger.info("Incoming query", extra={"query_id": query_id, "filters": req.filters.dict()})

    classification = classify_query(req.question)
    if not is_in_scope(classification):
        refusal_reason = (
            "This question appears to be outside the Online Safety Act scope. Please ask about the Act."
            if classification == QueryClassification.OUT_OF_SCOPE
            else (
                "This system cannot perform counts, rankings, or analytics-style "
                "questions. However, I can describe specific enforcement actions, "
                "duties, or regulatory approaches. Try rephrasing your question — "
                "for example, instead of 'how many platforms has Ofcom fined?', "
                "ask 'what enforcement actions has Ofcom taken under the Online Safety Act?'"
            )
        )
        answer = Answer(
            text=refusal_reason,
            confidence=Confidence(level="low", reason="Question flagged by scope guard."),
            refused=True,
            refusal_reason=refusal_reason,
            section_lock="off",
            allow_citations_on_refusal=False,
        )
        response = QueryResponse(
            answer=answer,
            citations=[],
            conflicts=[],
            evidence_pack=[],
            retrieved_sources=[],
            retrieval_debug=None,
            kb_status=_status_payload() if req.debug.include_kb_status else None,
            scope_classification=classification.value,
            definition_mode=False,
            status="refused",
            message_user=refusal_reason,
            suggestions=None,
            closest_matches=[],
            evidence_assessment=None,
        )
        logger.info(
            "Query rejected by scope guard",
            extra={"query_id": query_id, "classification": classification.value},
        )
        return response

    # --- Multi-turn: rewrite follow-up questions into standalone form ---
    effective_question = req.question
    rewritten_question = None
    if req.conversation_history and config.llm_configured():
        history_dicts = [turn.dict() for turn in req.conversation_history]
        effective_question, was_rewritten = rewrite_follow_up(
            req.question, history_dicts
        )
        if was_rewritten:
            rewritten_question = effective_question
            logger.info(
                "Follow-up rewritten",
                extra={"query_id": query_id, "original": req.question, "rewritten": effective_question},
            )

    retrieval_outcome = run_retrieval_plan(effective_question, req.filters, retriever)
    retrieval_context = retriever.last_context()
    candidates = retrieval_outcome.candidates
    retrieved_sources = [c.chunk for c in candidates]

    # --- Parliament data fetch (for strategic/parliamentary questions) ---
    parliament_context: dict = {}
    parliament_citations = []
    parliament_context_str = ""
    parliament_assessment: dict = {}
    synthesis_mode = "strategic" if needs_strategic_synthesis(classification, effective_question) else "factual"

    if needs_parliament_data(classification):
        parliament_context = fetch_parliament_context(
            effective_question, classification.value
        )
        parliament_citations = build_parliament_citations(parliament_context)
        if parliament_citations:
            parliament_context_str = format_parliament_evidence_context(
                parliament_context, parliament_citations
            )

    section_lock = apply_section_lock(effective_question, candidates, kb=loader.kb)
    answer_candidates = section_lock.filtered_candidates if section_lock.active else candidates
    evidence_pack = (
        build_evidence_pack(answer_candidates, section_locked=True) if section_lock.active else retrieval_outcome.evidence_pack
    )
    response_evidence = evidence_pack or []
    answer = None
    suggestions = None
    status_value = "success"
    message_user = ""
    closest_matches = []
    response_citations = []
    evidence_assessment = None
    evidence_signals = assess_evidence_sufficiency(effective_question, answer_candidates)

    # Assess Parliament evidence alongside KB evidence
    if parliament_context:
        parliament_assessment = assess_parliament_evidence(
            classification.value, parliament_context, evidence_signals
        )
    get_logger(
        __name__,
        extra={
            "section_lock_active": section_lock.active,
            "section_lock_has_matches": section_lock.has_matches,
            "section_lock_number": section_lock.section_number,
            "answer_candidates": len(answer_candidates),
            "filtered_candidates": len(section_lock.filtered_candidates),
            "evidence_pack": len(response_evidence),
            "evidence_belongs_count": sum(
                chunk_belongs_to_section(_section_match_text(chunk), str(section_lock.section_number or ""))
                for chunk in response_evidence
            ),
        },
    ).info("Section-lock debug")
    evidence_insufficient = (
        evidence_signals.status == "insufficient_evidence" or not response_evidence
    )
    # If KB evidence is insufficient but Parliament data was found, proceed anyway —
    # Parliament sources can provide sufficient basis for an answer.
    has_parliament_data = parliament_assessment.get("has_parliament_data", False)
    if evidence_insufficient and has_parliament_data:
        evidence_insufficient = False

    refusal = evidence_insufficient or should_refuse(answer_candidates, response_evidence)
    # Similarly, Parliament data overrides refusal for thin KB results
    if refusal and has_parliament_data:
        refusal = False
    answer_citations = build_citations(response_evidence)

    if req.use_llm and not config.llm_configured():
        missing = ", ".join(config.missing_llm_env())
        raise HTTPException(
            status_code=400,
            detail=f"LLM not configured. Set the following environment variables: {missing}",
        )

    if evidence_insufficient:
        # Build context-aware suggestions based on what was actually found
        active_cats = None
        all_cats = list(loader.kb.chunk_counts_by_type.keys()) if loader.kb.chunk_counts_by_type else None
        if all_cats:
            active_cats = _active_categories_for_filters(req.filters, all_cats)
        message_user, suggestions = contextual_suggestions(
            effective_question, answer_candidates, active_cats, all_cats
        )
        answer = Answer(
            text=message_user,
            confidence=Confidence(
                level="low",
                reason=(
                    "Insufficient evidence support: "
                    f"top score={evidence_signals.top_score:.2f}, "
                    f"coverage={evidence_signals.coverage:.2f}, "
                    f"separation={evidence_signals.separation:.2f}."
                ),
            ),
            refused=True,
            refusal_reason=message_user,
            section_lock=section_lock.label,
            allow_citations_on_refusal=False,
        )
        response_citations = []
        status_value = "insufficient_evidence"

    if not answer:
        use_llm = req.use_llm or config.llm_configured()
        if use_llm and config.llm_configured() and not refusal:
            strategic = needs_strategic_synthesis(classification, effective_question)
            answer = generate_llm_answer(
                effective_question,
                response_evidence,
                answer_citations,
                section_only=section_lock.active or retrieval_context.get("section_match", False),
                section_lock=section_lock.label,
                target_section=section_lock.section_number if section_lock.active else None,
                confidence_label=evidence_signals.confidence_label,
                conversation_history=(
                    [t.dict() for t in req.conversation_history]
                    if req.conversation_history else None
                ),
                strategic=strategic,
                parliament_context_str=parliament_context_str,
                parliament_note=parliament_assessment.get("parliament_note", ""),
                conflict_note=parliament_assessment.get("conflict_note"),
            )
            # Merge KB citations with Parliament citations
            response_citations = answer_citations + parliament_citations
            # If the LLM call itself failed, keep the helpful error message
            # rather than falling back to raw chunk dumps.
            if answer.refused and answer.refusal_reason in (
                "LLM synthesis error.",
                "LLM temporarily overloaded.",
            ):
                status_value = "llm_unavailable"
        else:
            answer = generate_answer(
                effective_question,
                [] if refusal else response_evidence,
                answer_citations,
                section_lock=section_lock.label,
                target_section=section_lock.section_number if section_lock.active else None,
            )
            response_citations = answer_citations
    # If the LLM itself refused (helpful refusal), surface its text and suggestions
    if answer and answer.refused and not evidence_insufficient and answer.refusal_reason:
        message_user = answer.text
        status_value = "insufficient_evidence"
        if not suggestions:
            all_cats = list(loader.kb.chunk_counts_by_type.keys()) if loader.kb.chunk_counts_by_type else None
            active_cats = _active_categories_for_filters(req.filters, all_cats) if all_cats else None
            _, suggestions = contextual_suggestions(
                effective_question, answer_candidates, active_cats, all_cats
            )

    if answer and not answer.refused:
        answer.confidence = Confidence(
            level=evidence_signals.confidence_label,
            reason=(
                f"Evidence signals — top score {evidence_signals.top_score:.2f}, "
                f"coverage {evidence_signals.coverage:.2f}, "
                f"separation {evidence_signals.separation:.2f}. "
                f"{answer.confidence.reason}"
            ),
        )
    log_usage(response_evidence)

    status = _status_payload() if req.debug.include_kb_status else None
    answer, citations, evidence_pack_out, retrieved_sources_out = enforce_response_consistency(
        answer=answer,
        citations=response_citations,
        evidence_pack=response_evidence,
        retrieved_sources=retrieved_sources,
        include_debug=req.debug.include_evidence_pack,
    )

    retrieval_debug = (
        _build_retrieval_debug(
            candidates, req.filters, section_lock, retrieval_outcome.definition_mode, retrieval_outcome.used_definition_candidates
        )
        if req.debug.include_retrieval_debug
        else None
    )

    # Compute source freshness from Parliament data
    source_freshness = compute_source_freshness(parliament_context) if parliament_context else None

    # Collect Parliament sources for transparency
    parliament_sources_out = None
    if parliament_context:
        sources = []
        sources.extend(parliament_context.get("written_answers", []))
        sources.extend(parliament_context.get("hansard_results", []))
        sources.extend(parliament_context.get("bills_data", []))
        if sources:
            parliament_sources_out = sources

    response = QueryResponse(
        answer=answer,
        citations=citations,
        conflicts=[],  # ROADMAP: populate with cross-source contradictions (see models.py)
        evidence_pack=evidence_pack_out,
        retrieved_sources=retrieved_sources_out,
        retrieval_debug=retrieval_debug,
        kb_status=status,
        scope_classification=classification.value,
        definition_mode=retrieval_outcome.definition_mode,
        status=status_value,
        message_user=message_user,
        suggestions=suggestions,
        closest_matches=closest_matches if status_value == "insufficient_evidence" else None,
        evidence_assessment=evidence_assessment,
        rewritten_question=rewritten_question,
        parliament_sources=parliament_sources_out,
        parliament_health=parliament_context.get("pipeline_health") if parliament_context else None,
        source_freshness=source_freshness,
        synthesis_mode=synthesis_mode,
    )

    logger.info(
        "Query handled",
        extra={
            "query_id": query_id,
            "refused": answer.refused,
            "citations": [c.citation_id for c in citations],
        },
    )
    return response


@app.get("/status")
@app.get("/api/status", include_in_schema=False)
def status() -> dict:
    return _status_payload()


@app.get("/healthz")
@app.get("/api/healthz", include_in_schema=False)
def healthz() -> dict:
    """Lightweight liveness probe."""
    return {"status": "ok", "version": __version__}


@app.get("/readyz")
@app.get("/api/readyz", include_in_schema=False)
def readyz() -> dict:
    """Readiness probe: requires KB loaded and retrieval index built."""
    ready = bool(loader.kb.last_refreshed) and retriever.index_ready
    payload = {
        "status": "ready" if ready else "not_ready",
        "kb_loaded": bool(loader.kb.last_refreshed),
        "index_ready": retriever.index_ready,
        "total_chunks": len(loader.kb.chunks),
        "version": __version__,
    }
    if not ready:
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.post("/refresh")
@app.post("/api/refresh", include_in_schema=False)
def refresh() -> dict:
    # Eager rebuild: build() invalidates the old embedding matrix,
    # rebuild_embeddings() regenerates it from the reloaded corpus before we
    # return. Front-loads the cost on the operator-triggered /refresh so the
    # first subsequent query sees the new chunks without a restart. Lazy
    # invalidation would keep refresh fast but shift the cost — and the
    # visibility — to the next query.
    loader.kb.load(config.KB_DIR)
    retriever.build()
    embeddings_rebuild = retriever.rebuild_embeddings()
    if not loader.kb.last_refreshed:
        raise HTTPException(status_code=500, detail="Failed to refresh knowledge base")
    payload = _status_payload()
    payload["embeddings_rebuild"] = embeddings_rebuild
    return payload


@app.post("/debug/retrieve", response_model=DebugRetrieveResponse)
@app.post("/api/debug/retrieve", response_model=DebugRetrieveResponse, include_in_schema=False)
def debug_retrieve(req: QueryRequest) -> DebugRetrieveResponse:
    """
    Debug-only: expose raw retrieval results without invoking any LLM.
    """
    candidates = retriever.retrieve(req.question, req.filters, top_k=config.MAX_RETRIEVAL_CANDIDATES)
    results: list[RetrievedChunkDebug] = []

    for cand in candidates:
        chunk = cand.chunk
        results.append(
            RetrievedChunkDebug(
                document_id=chunk.doc_id,
                title=chunk.title,
                category=chunk.source_type,
                page=chunk.location_pointer,
                header=chunk.header,
                excerpt=_debug_excerpt(chunk.chunk_text),
                relevance_score=cand.final_score,
                bm25_score=cand.bm25_score,
                embedding_score=cand.embedding_score,
            )
        )

    return DebugRetrieveResponse(
        results=results,
        retrieval_mode=retriever.effective_mode(),
        kb_status=_status_payload(),
    )


@app.get("/chunk/{chunk_id:path}")
@app.get("/api/chunk/{chunk_id:path}", include_in_schema=False)
def get_chunk(chunk_id: str) -> dict:
    """Return a single chunk by ID, for adjacent-chunk navigation."""
    chunk = next((c for c in loader.kb.chunks if c.chunk_id == chunk_id), None)
    if not chunk:
        raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")
    return {
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "title": chunk.title,
        "source_type": chunk.source_type,
        "header": chunk.header,
        "location_pointer": chunk.location_pointer,
        "chunk_text": chunk.chunk_text,
        "prev_chunk_id": chunk.prev_chunk_id,
        "next_chunk_id": chunk.next_chunk_id,
        "source_url": chunk.source_url,
        "source_format": chunk.source_format,
    }


@app.get("/kb-health")
@app.get("/api/kb-health", include_in_schema=False)
def kb_health() -> dict:
    """Return per-document quality metrics for the KB Health admin view."""
    import re

    # Group chunks by doc_id
    docs: dict = {}
    for chunk in loader.kb.chunks:
        if chunk.doc_id not in docs:
            docs[chunk.doc_id] = {
                "doc_id": chunk.doc_id,
                "title": chunk.title,
                "source_type": chunk.source_type,
                "source_format": getattr(chunk, "source_format", None),
                "source_url": getattr(chunk, "source_url", None),
                "total_chunks": 0,
                "has_url": bool(getattr(chunk, "source_url", None)),
            }
        docs[chunk.doc_id]["total_chunks"] += 1

    # Build per-document quality summary from metadata
    # We scan the raw JSON files for artifact scores since those aren't on the chunk model
    import json
    import glob
    import os

    kb_dir = config.KB_DIR
    for filepath in glob.glob(os.path.join(kb_dir, "**/*.json"), recursive=True):
        if "embeddings_cache" in filepath or ".cache" in filepath:
            continue
        try:
            with open(filepath) as f:
                data = json.load(f)
            meta = data.get("metadata", {})
            doc_id = meta.get("id") or meta.get("doc_id")
            if doc_id and doc_id in docs:
                docs[doc_id]["artifact_score"] = meta.get("pdf_artifact_score")
                # Derive category from path
                parts = filepath.split("/")
                for p in parts:
                    if p.startswith(("01_", "02_", "03_", "04_")):
                        docs[doc_id]["category"] = p
                        break
        except Exception:
            continue

    # Classify severity
    for doc in docs.values():
        score = doc.get("artifact_score")
        if score and score > 500:
            doc["severity"] = "high"
        elif score and score > 200:
            doc["severity"] = "medium"
        elif score and score > 50:
            doc["severity"] = "low"
        else:
            doc["severity"] = "clean"

    doc_list = sorted(docs.values(), key=lambda d: d.get("artifact_score") or 0, reverse=True)

    # Summary counts
    severity_counts = Counter(d["severity"] for d in doc_list)
    format_counts = Counter(d.get("source_format") or "Unknown" for d in doc_list)

    return {
        "total_docs": len(doc_list),
        "total_chunks": sum(d["total_chunks"] for d in doc_list),
        "severity_counts": dict(severity_counts),
        "format_counts": dict(format_counts),
        "url_coverage": sum(1 for d in doc_list if d.get("has_url")),
        "documents": doc_list,
    }


@app.get("/kb-stats")
@app.get("/api/kb-stats", include_in_schema=False)
def kb_stats() -> dict:
    """Return knowledge-base stats used by the sidebar and filter UI."""
    kb_status = loader.kb.status().dict()
    chunk_counts = kb_status.get("chunk_counts_by_type", {})
    return {
        "categories": chunk_counts,  # Backward-compatible alias for older UI code.
        "total_chunks": kb_status.get("total_chunks", 0),
        "doc_counts_by_type": kb_status.get("doc_counts_by_type", {}),
        "chunk_counts_by_type": chunk_counts,
        "last_refreshed": kb_status.get("last_refreshed"),
    }


def _safe_frontend_file(relative_path: str) -> Path | None:
    """Resolve a frontend static file path safely under FRONTEND_DIST_DIR."""
    if not FRONTEND_DIST_DIR.exists():
        return None
    base = FRONTEND_DIST_DIR.resolve()
    candidate = (base / relative_path).resolve()
    if candidate != base and base not in candidate.parents:
        return None
    if candidate.is_file():
        return candidate
    return None


@app.get("/", include_in_schema=False)
def frontend_index() -> FileResponse:
    index = _safe_frontend_file("index.html")
    if not index:
        raise HTTPException(status_code=404, detail="Frontend bundle not found")
    return FileResponse(index)


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa(full_path: str) -> FileResponse:
    # Leave API namespace for backend handlers / proper 404s.
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    asset = _safe_frontend_file(full_path)
    if asset:
        return FileResponse(asset)

    index = _safe_frontend_file("index.html")
    if not index:
        raise HTTPException(status_code=404, detail="Frontend bundle not found")
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
