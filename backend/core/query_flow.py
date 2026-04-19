from dataclasses import dataclass, field
from typing import List, Optional, Set

from backend import config
from backend.core.evidence import build_evidence_pack, expand_with_neighbors
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
    # chunk_ids of neighbours added by expand_with_neighbors — primaries are
    # every chunk in evidence_pack whose id is NOT in expansion_ids.
    expansion_ids: Set[str] = field(default_factory=set)


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
        definition_pack, definition_expansion_ids = expand_with_neighbors(
            definition_pack, retriever.kb
        )
        definition_top_score = definition_candidates[0].final_score if definition_candidates else 0.0
        if definition_candidates and definition_pack and definition_top_score >= config.MIN_RELEVANCE_SCORE:
            return RetrievalOutcome(
                candidates=definition_candidates,
                evidence_pack=definition_pack,
                top_score=definition_top_score,
                definition_mode=True,
                used_definition_candidates=True,
                definition_candidates=definition_candidates,
                expansion_ids=definition_expansion_ids,
            )

    candidates = retriever.retrieve(question, filters)
    evidence_pack = build_evidence_pack(candidates)
    evidence_pack, expansion_ids = expand_with_neighbors(evidence_pack, retriever.kb)
    top_score = candidates[0].final_score if candidates else 0.0

    return RetrievalOutcome(
        candidates=candidates,
        evidence_pack=evidence_pack,
        top_score=top_score,
        definition_mode=definition_mode,
        used_definition_candidates=False,
        definition_candidates=definition_candidates,
        expansion_ids=expansion_ids,
    )
