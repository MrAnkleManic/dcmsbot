from dataclasses import dataclass
from typing import List, Optional

from backend import config
from backend.core.evidence import build_evidence_pack
from backend.core.models import KBChunk, QueryFilters
from backend.core.query_guard import has_definition_intent
from backend.core.retriever import RetrievedChunk, Retriever


@dataclass
class RetrievalOutcome:
    candidates: List[RetrievedChunk]
    evidence_pack: List[KBChunk]
    top_score: float
    definition_mode: bool
    used_definition_candidates: bool
    definition_candidates: Optional[List[RetrievedChunk]] = None


def run_retrieval_plan(
    question: str,
    filters: QueryFilters,
    retriever: Retriever,
) -> RetrievalOutcome:
    definition_mode = has_definition_intent(question)
    definition_candidates: Optional[List[RetrievedChunk]] = None

    if definition_mode:
        definition_candidates = retriever.retrieve(
            question,
            filters,
            allowed_doc_types=config.DEFINITION_DOC_TYPES,
            override_filters=True,
        )
        definition_pack = build_evidence_pack(definition_candidates)
        definition_top_score = definition_candidates[0].final_score if definition_candidates else 0.0
        if definition_candidates and definition_pack and definition_top_score >= config.MIN_RELEVANCE_SCORE:
            return RetrievalOutcome(
                candidates=definition_candidates,
                evidence_pack=definition_pack,
                top_score=definition_top_score,
                definition_mode=True,
                used_definition_candidates=True,
                definition_candidates=definition_candidates,
            )

    candidates = retriever.retrieve(question, filters)
    evidence_pack = build_evidence_pack(candidates)
    top_score = candidates[0].final_score if candidates else 0.0

    return RetrievalOutcome(
        candidates=candidates,
        evidence_pack=evidence_pack,
        top_score=top_score,
        definition_mode=definition_mode,
        used_definition_candidates=False,
        definition_candidates=definition_candidates,
    )
