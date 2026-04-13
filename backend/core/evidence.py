import math
import re
from typing import List, Optional

from backend import config
from backend.core.guardrails import detect_definition_target, find_definition_snippet
from backend.core.llm_synthesis import synthesise_answer
from backend.core.models import Answer, Citation, Confidence, KBChunk
from backend.core.retriever import RetrievedChunk, chunk_belongs_to_section, _section_match_text
from backend.core.sections import chunk_section_number, parse_target_section
from backend.logging_config import get_logger

logger = get_logger(__name__)
_HEADING_PREFIX = re.compile(r"^Section heading:\s*", re.IGNORECASE)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[\.\?!])\s+")
_COMMENCEMENT_TERMS = ("commencement", "in force", "comes into force", "coming into force")


def _strip_heading_prefix(text: str) -> str:
    return _HEADING_PREFIX.sub("", text).strip()


def _excerpt(text: str, max_words: int = config.MAX_EXCERPT_WORDS) -> str:
    normalized = _strip_heading_prefix(text)
    words = normalized.split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]) + "..."


def _diversify_by_document(
    candidates: List[RetrievedChunk],
    max_per_doc: int = config.MAX_CHUNKS_PER_DOC,
    target_total: int = config.MAX_CHUNKS_TO_LLM,
) -> List[RetrievedChunk]:
    """
    Ensure chunks come from diverse documents.

    Keep at most *max_per_doc* chunks from any single document while
    preserving score ordering.  Return up to *target_total* chunks.
    """
    doc_counts: dict[str, int] = {}
    diverse: List[RetrievedChunk] = []

    for cand in candidates:
        doc_id = cand.chunk.doc_id
        count = doc_counts.get(doc_id, 0)
        if count < max_per_doc:
            diverse.append(cand)
            doc_counts[doc_id] = count + 1
        if len(diverse) >= target_total:
            break

    return diverse


def build_evidence_pack(
    candidates: List[RetrievedChunk],
    section_locked: bool = False,
) -> List[KBChunk]:
    if not candidates:
        return []

    # First pass: drop chunks below the minimum score threshold.
    max_score = candidates[0].final_score
    viable = [
        result
        for result in candidates
        if max_score > 0 and result.final_score / max_score >= config.MIN_SCORE_THRESHOLD
    ]

    # Second pass: diversify so no single document dominates.
    # When section-locked, allow more chunks from the same document
    # because legislative sections span multiple chunks.
    per_doc = 5 if section_locked else config.MAX_CHUNKS_PER_DOC
    diverse = _diversify_by_document(viable, max_per_doc=per_doc)

    # Third pass: deduplicate and enforce character budget.
    evidence: List[KBChunk] = []
    seen_keys: set[tuple[str, str | None]] = set()
    char_budget = 0
    for result in diverse:
        chunk = result.chunk
        key = (chunk.doc_id, chunk.location_pointer)
        if key in seen_keys:
            continue
        excerpt_len = len(chunk.chunk_text)
        if char_budget + excerpt_len > config.MAX_CHARS_TO_LLM:
            break
        seen_keys.add(key)
        evidence.append(chunk)
        char_budget += excerpt_len
    return evidence


def build_citations(evidence: List[KBChunk]) -> List[Citation]:
    citations: List[Citation] = []
    for idx, chunk in enumerate(evidence, start=1):
        citations.append(
            Citation(
                citation_id=f"C{idx:03d}",
                doc_id=chunk.doc_id,
                title=chunk.title,
                source_type=chunk.source_type,
                publisher=chunk.publisher,
                date_published=chunk.date_published,
                location_pointer=chunk.location_pointer,
                chunk_id=chunk.chunk_id,
                excerpt=_excerpt(chunk.chunk_text),
                authority_weight=chunk.authority_weight,
                source_url=chunk.source_url,
                prev_chunk_id=chunk.prev_chunk_id,
                next_chunk_id=chunk.next_chunk_id,
                source_format=chunk.source_format,
            )
        )
    return citations


def build_parliament_citations(parliament_context: dict) -> List[Citation]:
    """Build Citation objects from Parliament API results.

    Uses prefixes: WA### for Written Answers, H### for Hansard, B### for Bills.
    Authority weights: Written Answers (ministers) = 8.0, Hansard = 3.0, Bills = 7.0.
    """
    citations: List[Citation] = []

    # Written Answers — ministerial positions rank high
    for idx, wa in enumerate(parliament_context.get("written_answers", []), start=1):
        citations.append(
            Citation(
                citation_id=f"WA{idx:03d}",
                doc_id=f"parliament-wa-{wa.get('uin', idx)}",
                title=wa.get("title", "Written Answer"),
                source_type="Written Answer",
                publisher=wa.get("answering_body", "UK Parliament"),
                date_published=wa.get("date", None),
                location_pointer=f"Written Answer — {wa.get('answering_body', 'DCMS')}",
                chunk_id=f"wa-{wa.get('uin', idx)}",
                excerpt=_excerpt(wa.get("answer_text", wa.get("question_text", ""))),
                authority_weight=8.0,
                source_url=wa.get("url"),
                parliament_source_type="written_answer",
                parliament_date=wa.get("date"),
            )
        )

    # Hansard debates
    for idx, h in enumerate(parliament_context.get("hansard_results", []), start=1):
        citations.append(
            Citation(
                citation_id=f"H{idx:03d}",
                doc_id=f"parliament-hansard-{h.get('external_id', idx)}",
                title=h.get("title", "Hansard Debate"),
                source_type="Hansard Debate",
                publisher="UK Parliament",
                date_published=h.get("date", None),
                location_pointer=f"{h.get('house', 'Commons')} — {h.get('section', 'Debate')}",
                chunk_id=f"hansard-{h.get('external_id', idx)}",
                excerpt=h.get("title", "Parliamentary debate"),
                authority_weight=3.0,
                source_url=h.get("url"),
                parliament_source_type="hansard_debate",
                parliament_date=h.get("date"),
            )
        )

    # Bills
    for idx, b in enumerate(parliament_context.get("bills_data", []), start=1):
        stage = b.get("current_stage", "Unknown stage")
        status_label = "Act of Parliament" if b.get("is_act") else f"Bill — {stage}"
        citations.append(
            Citation(
                citation_id=f"B{idx:03d}",
                doc_id=f"parliament-bill-{idx}",
                title=b.get("short_title", "Bill"),
                source_type="Bill",
                publisher="UK Parliament",
                date_published=None,
                location_pointer=status_label,
                chunk_id=f"bill-{idx}",
                excerpt=f"{b.get('short_title', 'Bill')} — {status_label}",
                authority_weight=7.0,
                source_url=b.get("url"),
                parliament_source_type="bill",
                parliament_date=None,
            )
        )

    return citations


def find_citation_for_chunk(chunk: KBChunk, citations: List[Citation]) -> Optional[Citation]:
    for citation in citations:
        if citation.chunk_id == chunk.chunk_id:
            return citation
    return None


def format_parliament_evidence_context(parliament_context: dict, citations: List[Citation]) -> str:
    """Format Parliament data as evidence context blocks for the LLM prompt.

    Each block is labelled with its citation ID so the LLM can cite [WA001] etc.
    """
    parts: list[str] = []
    cit_idx = 0

    for wa in parliament_context.get("written_answers", []):
        if cit_idx >= len(citations):
            break
        cit = citations[cit_idx]
        cit_idx += 1
        text = wa.get("answer_text", "")
        if not text:
            text = wa.get("question_text", "No answer text available.")
        header = f"[{cit.citation_id}] Written Answer — {wa.get('answering_body', 'DCMS')}"
        if wa.get("date"):
            header += f" ({wa['date']})"
        header += f" (source_type: Written Answer, authority_weight: {cit.authority_weight})"
        q_text = wa.get("question_text", "")
        block = f"Question: {q_text}\nAnswer: {text}" if q_text else text
        parts.append(f"{header}\n{block}")

    for h in parliament_context.get("hansard_results", []):
        if cit_idx >= len(citations):
            break
        cit = citations[cit_idx]
        cit_idx += 1
        header = f"[{cit.citation_id}] Hansard Debate — {h.get('title', 'Debate')}"
        if h.get("date"):
            header += f" ({h['date']})"
        header += f" (source_type: Hansard Debate, authority_weight: {cit.authority_weight})"
        parts.append(f"{header}\n{h.get('title', 'Parliamentary debate')} — {h.get('house', '')} {h.get('section', '')}")

    for b in parliament_context.get("bills_data", []):
        if cit_idx >= len(citations):
            break
        cit = citations[cit_idx]
        cit_idx += 1
        stage = b.get("current_stage", "Unknown stage")
        status = "Act of Parliament" if b.get("is_act") else f"Bill — {stage}"
        header = f"[{cit.citation_id}] {b.get('short_title', 'Bill')} — {status}"
        header += f" (source_type: Bill, authority_weight: {cit.authority_weight})"
        parts.append(header)

    return "\n\n---\n\n".join(parts)


def compute_source_freshness(parliament_context: dict) -> str | None:
    """Find the most recent date across all Parliament sources."""
    dates: list[str] = []
    for wa in parliament_context.get("written_answers", []):
        d = wa.get("date")
        if d:
            dates.append(d)
    for h in parliament_context.get("hansard_results", []):
        d = h.get("date")
        if d:
            dates.append(d)
    if not dates:
        return None
    dates.sort(reverse=True)
    newest = dates[0]
    # Try to format nicely
    try:
        from datetime import datetime
        dt = datetime.strptime(newest[:10], "%Y-%m-%d")
        return f"Most recent Parliament source: {dt.strftime('%d %B %Y')}"
    except (ValueError, IndexError):
        return f"Most recent Parliament source: {newest}"


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_sentences(text: str, max_sentences: int = 2) -> List[str]:
    cleaned = _normalize_whitespace(_strip_heading_prefix(text))
    if not cleaned:
        return []
    parts = _SENTENCE_BOUNDARY.split(cleaned)
    sentences: List[str] = []
    for part in parts:
        sentence = part.strip()
        if not sentence:
            continue
        if len(sentence.split()) < 3:
            continue
        if not re.search(r"[\.!?]$", sentence):
            if len(sentence.split()) < 6:
                continue
        sentences.append(sentence)
        if len(sentences) >= max_sentences:
            break
    if not sentences:
        sentences.append(cleaned)
    return sentences


def _format_location(citation: Citation) -> str:
    if citation.location_pointer:
        return f", {citation.location_pointer}"
    return ""


def _question_mentions_commencement(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in _COMMENCEMENT_TERMS)


def _evidence_shows_commencement(evidence: List[KBChunk]) -> bool:
    for chunk in evidence:
        text = chunk.chunk_text.lower()
        if any(term in text for term in _COMMENCEMENT_TERMS):
            return True
    return False


def _has_exact_section_match(evidence: List[KBChunk], target_section: int | None) -> tuple[bool, bool]:
    if target_section is None:
        return False, False
    exact_chunks = [
        chunk
        for chunk in evidence
        if chunk_section_number(chunk) == target_section
        or chunk_belongs_to_section(_section_match_text(chunk), str(target_section))
    ]
    if not exact_chunks:
        return False, False
    primary_matches = [chunk for chunk in exact_chunks if chunk.source_type.lower() == "act of parliament"]
    return bool(exact_chunks), bool(primary_matches)


def _confidence_level(
    evidence: List[KBChunk],
    target_section: int | None,
) -> Confidence:
    if not evidence:
        return Confidence(level="low", reason="No supporting evidence was available.")
    has_match, has_primary = _has_exact_section_match(evidence, target_section)
    if target_section is None:
        return Confidence(level="medium", reason="Answer based on retrieved evidence excerpts.")
    if has_primary:
        return Confidence(level="high", reason="Exact section match from primary legislation.")
    if has_match:
        return Confidence(level="medium", reason="Section match found in secondary or contextual material.")
    return Confidence(level="low", reason="Exact section match not present in retrieved evidence.")


def _build_missing_lines(
    question: str, evidence: List[KBChunk], target_section: int | None
) -> list[str]:
    missing: list[str] = []
    definition_target = detect_definition_target(question)
    if definition_target:
        snippet = find_definition_snippet(definition_target, evidence)
        if not snippet:
            missing.append(f'Definition of "{definition_target}" is not shown in the retrieved evidence.')
    if _question_mentions_commencement(question) and not _evidence_shows_commencement(evidence):
        missing.append("Commencement / in-force status is not shown in the retrieved evidence.")
    if target_section is not None:
        has_match, _ = _has_exact_section_match(evidence, target_section)
        if not has_match:
            missing.append("Exact section match not found in retrieved evidence.")
    return missing


def _format_answer_lines(
    evidence: List[KBChunk],
    citations: List[Citation],
    missing_lines: List[str],
) -> str:
    lines: list[str] = []
    warning_line = next(
        (line for line in missing_lines if line.lower().startswith("exact section match")), None
    )
    if warning_line:
        lines.append(f"Warning: {warning_line}")
    lines.append("Answer")
    if not evidence:
        lines.append("- No supporting evidence available.")
        if missing_lines:
            lines.append("Not shown in retrieved evidence")
            lines.extend(f"- {m}" for m in missing_lines)
        return "\n".join(lines)

    max_items = 3
    for chunk, citation in zip(evidence[:max_items], citations[:max_items]):
        sentences = _extract_sentences(chunk.chunk_text, max_sentences=2)
        quote = _normalize_whitespace(" ".join(sentences[:2]))
        location = _format_location(citation)
        lines.append(f'- From {citation.citation_id} ({citation.title}{location}): "{quote}"')
    remaining = max(len(evidence) - max_items, 0)
    if remaining:
        lines.append(f"...plus {remaining} more evidence item(s) available below.")

    if missing_lines:
        lines.append("Not shown in retrieved evidence")
        lines.extend(f"- {line}" for line in missing_lines)
    return "\n".join(lines)


def generate_answer(
    question: str,
    evidence: List[KBChunk],
    citations: List[Citation],
    section_lock: str | None = None,
    target_section: int | None = None,
) -> Answer:
    if target_section is None:
        target_section = parse_target_section(question)
    if not evidence:
        return Answer(
            text=(
                "I cannot answer this question from the current knowledge base. "
                "No relevant evidence found for this question."
            ),
            confidence=Confidence(level="low", reason="No relevant evidence was available."),
            refused=True,
            refusal_reason="No relevant evidence was available to support an answer.",
            section_lock=section_lock,
        )

    missing_lines = _build_missing_lines(question, evidence, target_section)
    answer_text = _format_answer_lines(evidence, citations, missing_lines)
    confidence = _confidence_level(evidence, target_section)

    return Answer(
        text=answer_text,
        confidence=confidence,
        refused=False,
        refusal_reason=None,
        section_lock=section_lock,
    )


def generate_llm_answer(
    question: str,
    evidence: List[KBChunk],
    citations: List[Citation],
    section_only: bool = False,
    section_lock: str | None = None,
    target_section: int | None = None,
    confidence_label: str = "medium",
    conversation_history: Optional[List[dict]] = None,
    strategic: bool = False,
    parliament_context_str: str = "",
    parliament_note: str = "",
    conflict_note: str | None = None,
) -> Answer:
    """Generate an answer using LLM synthesis over retrieved evidence."""
    if target_section is None:
        target_section = parse_target_section(question)
    return synthesise_answer(
        question=question,
        evidence=evidence,
        citations=citations,
        section_lock=section_lock,
        target_section=target_section,
        confidence_label=confidence_label,
        conversation_history=conversation_history,
        strategic=strategic,
        parliament_context_str=parliament_context_str,
        parliament_note=parliament_note,
        conflict_note=conflict_note,
    )


def enforce_response_consistency(
    answer: Answer,
    citations: List[Citation],
    evidence_pack: List[KBChunk],
    retrieved_sources: List[KBChunk],
    include_debug: bool,
) -> tuple[Answer, List[Citation], Optional[List[KBChunk]], Optional[List[KBChunk]]]:
    """
    Ensure refusal/citation consistency and separate retrieved context from supporting sources.

    Returns the potentially updated answer, citations, evidence_pack (if surfaced),
    and retrieved_sources (if surfaced).
    """

    debug_evidence = evidence_pack if include_debug else None
    debug_retrieval = retrieved_sources if include_debug else None

    if answer.refused:
        if answer.allow_citations_on_refusal:
            return answer, citations, debug_evidence, debug_retrieval
        return answer, [], ([] if include_debug else None), debug_retrieval

    if not citations:
        downgraded = Answer(
            text="I cannot provide a supported answer. No supporting evidence was used.",
            confidence=Confidence(level="low", reason="No supporting sources available."),
            refused=True,
            refusal_reason="No supporting evidence was used.",
        )
        return downgraded, [], ([] if include_debug else None), debug_retrieval

    return answer, citations, debug_evidence, debug_retrieval


def should_refuse(candidates: List[RetrievedChunk], evidence: List[KBChunk]) -> bool:
    if not candidates or not evidence:
        return True
    top_score = candidates[0].final_score
    return top_score < config.MIN_RELEVANCE_SCORE


def log_usage(evidence: List[KBChunk]) -> None:
    total_chars = sum(len(ch.chunk_text) for ch in evidence)
    est_tokens = math.ceil(total_chars * config.TOKEN_BUDGET_ESTIMATE_PER_CHAR)
    logger.info(
        "Evidence pack size",
        extra={
            "chunks": len(evidence),
            "chars": total_chars,
            "est_tokens": est_tokens,
        },
    )
