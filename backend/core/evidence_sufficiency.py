from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Set

from backend import config
from backend.core.models import KBChunk
from backend.core.retriever import RetrievedChunk
from backend.core.sections import parse_target_section, section_matches_chunk

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9']+")
_STOPWORDS: Set[str] = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "them",
    "this",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
}


@dataclass
class EvidenceSignals:
    status: str
    top_score: float
    coverage: float
    separation: float
    confidence_label: str


def _content_tokens(text: str) -> Set[str]:
    tokens = [t.lower() for t in _TOKEN_PATTERN.findall(text)]
    return {t for t in tokens if len(t) > 2 and t not in _STOPWORDS}


def _coverage_score(query: str, chunks: Iterable[KBChunk], top_k: int) -> float:
    tokens = _content_tokens(query)
    if not tokens:
        return 0.0
    sampled_chunks = list(chunks)[:top_k]
    if not sampled_chunks:
        return 0.0
    matches = set()
    for token in tokens:
        token_re = re.compile(rf"\b{re.escape(token)}\b")
        for chunk in sampled_chunks:
            combined = " ".join(
                [
                    chunk.chunk_text or "",
                    chunk.title or "",
                    chunk.header or "",
                    chunk.location_pointer or "",
                ]
            ).lower()
            if token_re.search(combined):
                matches.add(token)
                break
    return len(matches) / len(tokens)


def _score_separation(candidates: list[RetrievedChunk]) -> float:
    if len(candidates) < 2:
        return math.inf
    s1 = candidates[0].final_score
    s2 = candidates[1].final_score
    return s1 / (s2 + 1e-6)


def _confidence_from_signals(top_score: float, coverage: float, separation: float) -> str:
    strong_top = top_score >= config.EVIDENCE_MIN_TOP_SCORE * 1.5
    strong_coverage = coverage >= config.EVIDENCE_MIN_COVERAGE * 1.5
    strong_separation = separation >= config.EVIDENCE_MIN_SEPARATION * 1.2
    if strong_top and strong_coverage and strong_separation:
        return "high"
    if top_score >= config.EVIDENCE_MIN_TOP_SCORE and coverage >= config.EVIDENCE_MIN_COVERAGE:
        return "medium"
    return "low"


def assess_evidence_sufficiency(question: str, candidates: list[RetrievedChunk]) -> EvidenceSignals:
    if not candidates:
        return EvidenceSignals(
            status="insufficient_evidence",
            top_score=0.0,
            coverage=0.0,
            separation=0.0,
            confidence_label="low",
        )

    top_score = candidates[0].final_score
    separation = _score_separation(candidates)
    coverage = _coverage_score(
        question,
        (cand.chunk for cand in candidates),
        top_k=config.EVIDENCE_TOP_K_FOR_COVERAGE,
    )

    # Hybrid retrieval (BM25 + embeddings) needs relaxed thresholds:
    #   - Tight separation is EXPECTED because embeddings return
    #     semantically similar chunks with similar scores.
    #   - Keyword coverage is a weak signal because the question's
    #     vocabulary often differs from the source text (a question
    #     about "criticism" matches debate chunks that don't contain
    #     the word "criticism" because semantics match).
    # Without relaxing, every hybrid query gets refused.
    hybrid_active = any(
        (getattr(c, "embedding_score", 0) or 0) > 0 for c in candidates[:5]
    )
    if hybrid_active:
        separation_threshold = 1.005
        coverage_threshold = 0.2
    else:
        separation_threshold = config.EVIDENCE_MIN_SEPARATION
        coverage_threshold = config.EVIDENCE_MIN_COVERAGE

    insufficient = (
        top_score < config.EVIDENCE_MIN_TOP_SCORE
        or coverage < coverage_threshold
        or separation < separation_threshold
    )

    # Override: direct section match from high-authority source always passes
    if insufficient:
        target_section = parse_target_section(question)
        if target_section is not None:
            for cand in candidates:
                chunk = cand.chunk
                if section_matches_chunk(chunk, target_section) and chunk.authority_weight >= 8.0:
                    insufficient = False
                    break

    # Override: multi-source authority — multiple Act chunks + supporting material
    if insufficient:
        act_chunks = [c for c in candidates if c.chunk.authority_weight >= 8]
        supporting_chunks = [c for c in candidates if c.chunk.authority_weight >= 4]
        if len(act_chunks) >= 2 and len(supporting_chunks) >= 5:
            insufficient = False

    status = "insufficient_evidence" if insufficient else "ok"
    confidence_label = _confidence_from_signals(top_score, coverage, separation)

    return EvidenceSignals(
        status=status,
        top_score=top_score,
        coverage=coverage,
        separation=separation,
        confidence_label=confidence_label,
    )


def assess_parliament_evidence(
    classification: str,
    parliament_context: dict,
    kb_evidence_signals: EvidenceSignals,
) -> dict:
    """Assess Parliament evidence and produce supplementary notes for synthesis.

    Returns dict with:
        parliament_note: str — note to include in the LLM context about Parliament data
        has_parliament_data: bool
        freshness_note: str | None — date of most recent source
        conflict_note: str | None — if KB and Parliament sources may conflict
    """
    from backend.core.evidence import compute_source_freshness

    wa_count = len(parliament_context.get("written_answers", []))
    hansard_count = len(parliament_context.get("hansard_results", []))
    bills_count = len(parliament_context.get("bills_data", []))
    has_data = wa_count > 0 or hansard_count > 0 or bills_count > 0

    notes: list[str] = []
    freshness = compute_source_freshness(parliament_context)

    if classification == "IN_SCOPE_PARLIAMENTARY" and not has_data:
        notes.append(
            "No recent parliamentary activity found on this topic. "
            "Answer is based on static legislation and guidance."
        )
    elif has_data and freshness:
        notes.append(freshness)

    # Note about combining sources
    conflict_note = None
    if has_data and kb_evidence_signals.status == "ok":
        conflict_note = (
            "Evidence includes both static KB sources and live Parliament data. "
            "If these sources present different positions, surface both with dates. "
            "Do not pick one — present the discrepancy clearly."
        )

    return {
        "parliament_note": " ".join(notes) if notes else "",
        "has_parliament_data": has_data,
        "freshness_note": freshness,
        "conflict_note": conflict_note,
    }


def default_suggestions() -> list[str]:
    return [
        'Try asking for a specific section (e.g., "What does section 12 say?").',
        'Try naming a defined term (e.g., "user-to-user service").',
        "If this is about Ofcom practice, enable Regulator Guidance in source filters.",
        "Add more context or keywords that appear in the source material.",
    ]


def contextual_suggestions(
    question: str,
    candidates: list["RetrievedChunk"],
    active_categories: list[str] | None = None,
    all_categories: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Build a context-aware refusal message and suggestions based on what was found.

    Returns (summary_message, suggestions_list).
    """
    from backend.core.doc_types import canonical_doc_type

    if not candidates:
        return (
            "I couldn't find any evidence in the current knowledge base matching your question.",
            default_suggestions(),
        )

    # Analyse what was found
    top_chunks = candidates[:10]
    source_types: dict[str, int] = {}
    topics_seen: set[str] = set()
    for cand in top_chunks:
        doc_type = canonical_doc_type(cand.chunk.source_type)
        source_types[doc_type] = source_types.get(doc_type, 0) + 1
        if cand.chunk.location_pointer:
            topics_seen.add(cand.chunk.location_pointer)

    # Build summary of what was found
    found_parts: list[str] = []
    for doc_type, count in sorted(source_types.items(), key=lambda x: -x[1]):
        sample_locations = [
            c.chunk.location_pointer
            for c in top_chunks
            if canonical_doc_type(c.chunk.source_type) == doc_type and c.chunk.location_pointer
        ][:3]
        loc_str = f" (mentioning {', '.join(sample_locations)})" if sample_locations else ""
        found_parts.append(f"{count} chunk(s) from {doc_type}{loc_str}")

    found_summary = "; ".join(found_parts)
    message = (
        f"I couldn't find strong enough evidence to answer that reliably. "
        f"Here's what was closest: {found_summary}."
    )

    # Build contextual suggestions
    suggestions: list[str] = []

    # Suggest breaking down compound questions
    query_lower = question.lower()
    comparison_words = ["compare", "vs", "versus", "difference", "between"]
    if any(w in query_lower for w in comparison_words):
        # Extract key terms to suggest individual questions
        suggestions.append(
            "This looks like a comparison question. Try asking about each topic separately, then compare the answers yourself."
        )

    # Suggest specific sections if we found nearby content
    if topics_seen:
        section_refs = [t for t in topics_seen if t.lower().startswith("section")][:3]
        if section_refs:
            for ref in section_refs[:2]:
                suggestions.append(f'Try asking: "What does {ref} say?"')

    # Suggest enabling disabled source categories
    if active_categories and all_categories:
        disabled = set(all_categories) - set(active_categories)
        if disabled:
            disabled_str = ", ".join(sorted(disabled))
            suggestions.append(
                f"Some document sources are currently filtered out ({disabled_str}). "
                "Try enabling them in source filters."
            )

    # Fallback suggestions
    if len(suggestions) < 2:
        suggestions.extend(default_suggestions())

    return message, suggestions[:5]
