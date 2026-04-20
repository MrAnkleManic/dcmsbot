from dataclasses import dataclass, field
from typing import List, Optional, Set

from backend import config
from backend.core.evidence import PackConfig, build_evidence_pack, expand_with_neighbors
from backend.core.models import KBChunk, QueryFilters
import re

from backend.core.query_classifier import QueryKindResult, classify_query_kind
from backend.core.query_guard import _STRATEGIC_PATTERNS, has_definition_intent
from backend.core.retriever import RetrievedChunk, Retriever


@dataclass(frozen=True)
class RetrievalCoverage:
    """Honest-framing metadata surfaced to the synthesis layer.

    Lets the LLM distinguish retrieval-depth-limited answers (many
    matching chunks exist, pack is a thin slice) from corpus-sparse
    answers (few matching chunks exist in the first place). See
    open-threads #83 / Brief 9 sub-job C.
    """
    requested: int        # top_k asked of the retriever
    returned: int         # candidates retriever actually returned
    pack_size: int        # chunks that survived evidence-pack shaping
    corpus_matches: int   # chunks containing >= N content tokens from the query
    kind: str             # "survey" | "factual"

    @property
    def coverage_ratio(self) -> float:
        if self.corpus_matches <= 0:
            return 1.0
        return self.pack_size / self.corpus_matches

    @property
    def is_retrieval_limited(self) -> bool:
        """True when retrieval-depth is the bottleneck, not corpus sparsity.

        Gated on RETRIEVAL_LIMITED_COVERAGE_THRESHOLD and a minimum
        corpus_matches — single-digit matches aren't a retrieval
        problem, they're just a sparse corpus.
        """
        if self.corpus_matches < 10:
            return False
        return self.coverage_ratio <= config.RETRIEVAL_LIMITED_COVERAGE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            "requested": self.requested,
            "returned": self.returned,
            "pack_size": self.pack_size,
            "corpus_matches": self.corpus_matches,
            "kind": self.kind,
            "coverage_ratio": round(self.coverage_ratio, 4),
            "is_retrieval_limited": self.is_retrieval_limited,
        }


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
    # Classification of the incoming query (survey vs factual) — drives
    # the evidence-pack widening above and feeds retrieval_coverage
    # metadata into the synthesis layer.
    query_kind: QueryKindResult = field(
        default_factory=lambda: QueryKindResult(kind="factual", signals=[])
    )
    # Retrieval-vs-corpus framing metadata; forwarded to the synthesis
    # layer so the LLM can frame limitations honestly.
    retrieval_coverage: Optional[RetrievalCoverage] = None


_NARRATIVE_PATTERNS = [
    re.compile(r"\bhappened\b", re.IGNORECASE),
    re.compile(r"\bchanged\b", re.IGNORECASE),
    re.compile(r"\bbecame\b", re.IGNORECASE),
    re.compile(r"\bbetween\s+.*\band\b", re.IGNORECASE),
    re.compile(r"\bduring the\s+(bill|act|passage|debate)", re.IGNORECASE),
    re.compile(r"\bpassage of\b", re.IGNORECASE),
    re.compile(r"\bfrom\s+(first|draft|introduction).*\bto\b", re.IGNORECASE),
    re.compile(r"\bcriticism\b", re.IGNORECASE),
    re.compile(r"\brespond(ed|ing)?\b", re.IGNORECASE),
    re.compile(r"\bconcerns?\b", re.IGNORECASE),
    re.compile(r"\bargu(ed|ment|ments)\b", re.IGNORECASE),
    re.compile(r"\bposition(s)?\b", re.IGNORECASE),
    re.compile(r"\bdisagree(d|ment)?\b", re.IGNORECASE),
    re.compile(r"\bdebate(d|s)?\b", re.IGNORECASE),
    re.compile(r"\bamend(ed|ment|ments)\b", re.IGNORECASE),
    re.compile(r"\brecommend(ed|ation|ations)\b", re.IGNORECASE),
    re.compile(r"\binfluenc(e|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\bshap(e|ed|ing)\b", re.IGNORECASE),
    re.compile(r"\brole\b", re.IGNORECASE),
]


def _has_strategic_signal(question: str) -> bool:
    """True when the question phrasing signals narrative/interpretive
    intent — triggers the voice-rich pack tilt so Hansard and written
    evidence surface alongside the Act and guidance. Covers both
    strategic analysis language and narrative/evolution markers."""
    if any(p.search(question) for p in _STRATEGIC_PATTERNS):
        return True
    return any(p.search(question) for p in _NARRATIVE_PATTERNS)


def _pack_config_for(kind: str, question: str = "") -> PackConfig:
    # Narrative tilt wins even on survey questions — a question like
    # "what happened to X between the first draft and Royal Assent?"
    # is both a survey AND needs voice-rich sources.
    if question and _has_strategic_signal(question):
        return PackConfig.for_narrative()
    if kind == "survey":
        return PackConfig.for_survey()
    return PackConfig.default()


def _top_k_for(kind: str) -> int:
    return config.SURVEY_RETRIEVAL_TOP_K if kind == "survey" else config.MAX_RETRIEVAL_CANDIDATES


def run_retrieval_plan(
    question: str,
    filters: QueryFilters,
    retriever: Retriever,
    query_kind: Optional[QueryKindResult] = None,
) -> RetrievalOutcome:
    definition_mode = has_definition_intent(question)
    definition_candidates: Optional[List[RetrievedChunk]] = None

    if query_kind is None:
        query_kind = classify_query_kind(question)

    pack_cfg = _pack_config_for(query_kind.kind, question)
    top_k = _top_k_for(query_kind.kind)

    if definition_mode:
        definition_candidates = retriever.retrieve(
            question,
            filters,
            top_k=top_k,
            allowed_doc_types=config.DEFINITION_DOC_TYPES,
            override_filters=True,
        )
        definition_pack = build_evidence_pack(definition_candidates, pack_config=pack_cfg)
        definition_pack, definition_expansion_ids = expand_with_neighbors(
            definition_pack, retriever.kb, max_chars=pack_cfg.max_chars_to_llm
        )
        definition_top_score = definition_candidates[0].final_score if definition_candidates else 0.0
        if definition_candidates and definition_pack and definition_top_score >= config.MIN_RELEVANCE_SCORE:
            # Report pack_size as primaries only (excluding neighbour expansions).
            definition_primaries = [
                c for c in definition_pack if c.chunk_id not in definition_expansion_ids
            ]
            coverage = RetrievalCoverage(
                requested=top_k,
                returned=len(definition_candidates),
                pack_size=len(definition_primaries),
                corpus_matches=int(retriever.last_context().get("corpus_matches", 0) or 0),
                kind=query_kind.kind,
            )
            return RetrievalOutcome(
                candidates=definition_candidates,
                evidence_pack=definition_pack,
                top_score=definition_top_score,
                definition_mode=True,
                used_definition_candidates=True,
                definition_candidates=definition_candidates,
                expansion_ids=definition_expansion_ids,
                query_kind=query_kind,
                retrieval_coverage=coverage,
            )

    candidates = retriever.retrieve(question, filters, top_k=top_k)
    evidence_pack = build_evidence_pack(candidates, pack_config=pack_cfg)
    evidence_pack, expansion_ids = expand_with_neighbors(
        evidence_pack, retriever.kb, max_chars=pack_cfg.max_chars_to_llm
    )
    top_score = candidates[0].final_score if candidates else 0.0

    # pack_size counts primary chunks only — the neighbour expansion is
    # contextual padding, not independently-retrieved evidence.
    primaries = [c for c in evidence_pack if c.chunk_id not in expansion_ids]
    coverage = RetrievalCoverage(
        requested=top_k,
        returned=len(candidates),
        pack_size=len(primaries),
        corpus_matches=int(retriever.last_context().get("corpus_matches", 0) or 0),
        kind=query_kind.kind,
    )

    return RetrievalOutcome(
        candidates=candidates,
        evidence_pack=evidence_pack,
        top_score=top_score,
        definition_mode=definition_mode,
        used_definition_candidates=False,
        definition_candidates=definition_candidates,
        expansion_ids=expansion_ids,
        query_kind=query_kind,
        retrieval_coverage=coverage,
    )
