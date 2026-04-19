from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, Field, validator

from backend import config


class KBChunk(BaseModel):
    doc_id: str
    title: str
    source_type: str
    publisher: str
    date_published: Optional[str]
    chunk_id: str
    chunk_text: str
    header: Optional[str] = None
    location_pointer: Optional[str] = None
    authority_weight: float = 1.0
    reliability_flags: Optional[List[str]] = None
    # Extended fields for BotCleaner compatibility (bottl KB Standard v1.0)
    speaker: Optional[str] = None
    turn_index: Optional[int] = None
    column_ref: Optional[str] = None
    section_number: Optional[str] = None
    page: Optional[Union[int, str]] = None  # Can be int (page number) or "All"
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    chunk_hash: Optional[str] = None
    source_url: Optional[str] = None
    source_format: Optional[str] = None  # e.g. "PDF (pdfplumber)", "HTML", "Unknown"

    @validator("chunk_text")
    def strip_text(cls, v: str) -> str:
        return v.strip()


class Citation(BaseModel):
    citation_id: str
    doc_id: str
    title: str
    source_type: str
    publisher: str
    date_published: Optional[str]
    location_pointer: Optional[str]
    chunk_id: str
    excerpt: str
    authority_weight: float
    source_url: Optional[str] = None
    prev_chunk_id: Optional[str] = None
    next_chunk_id: Optional[str] = None
    source_format: Optional[str] = None
    # Parliament-specific fields (set for WA/H/B citations, None for KB)
    parliament_source_type: Optional[str] = None  # "written_answer", "hansard_debate", "bill"
    parliament_date: Optional[str] = None  # date of the WA/debate/bill activity
    # True when this citation was pulled in as a K-1/K+1 neighbour of a primary
    # to keep chunks from cutting off mid-sentence, not independently scored.
    is_expansion: bool = False


class Confidence(BaseModel):
    level: str
    reason: str


class Answer(BaseModel):
    text: str
    confidence: Confidence
    refused: bool
    refusal_reason: Optional[str] = None
    section_lock: Optional[str] = None
    allow_citations_on_refusal: bool = False


class ConversationTurn(BaseModel):
    """A single turn in a multi-turn conversation."""
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1)


class QueryFilters(BaseModel):
    primary_only: bool = Field(default=False)
    include_guidance: bool = Field(default=True)
    include_debates: bool = Field(default=True)
    enabled_categories: Optional[List[str]] = Field(
        default=None,
        description="When set, only chunks from these canonical doc types are included. Overrides primary_only/include_guidance/include_debates.",
    )


class QueryDebug(BaseModel):
    include_evidence_pack: bool = False
    include_kb_status: bool = False
    include_retrieval_debug: bool = False


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3)
    filters: QueryFilters = Field(
        default_factory=lambda: QueryFilters(**config.DEFAULT_FILTERS)
    )
    debug: QueryDebug = QueryDebug()
    use_llm: bool = False
    conversation_history: Optional[List[ConversationTurn]] = None


class RetrievalDebugEntry(BaseModel):
    rank: int
    doc_id: str
    chunk_id: str
    doc_type: str
    raw_doc_type: Optional[str] = None
    title: str
    date: Optional[str]
    section: Optional[str]
    location_pointer: Optional[str]
    relevance_score: float
    bm25_score: float
    embedding_score: Optional[float]
    reason_flags: List[str] = Field(default_factory=list)


class RetrievalDebugSummary(BaseModel):
    filters: Dict
    section_lock: str
    retrieval_mode: Optional[str] = None
    doc_type_breakdown: Dict[str, int] = Field(default_factory=dict)
    definition_mode: Optional[bool] = None
    definition_route_used: Optional[bool] = None


class RetrievalDebug(BaseModel):
    summary: RetrievalDebugSummary
    results: List[RetrievalDebugEntry] = Field(default_factory=list)


class EvidenceAssessment(BaseModel):
    status: str
    top_score: float
    coverage: float
    separation: float
    confidence_label: str


class QueryResponse(BaseModel):
    answer: Answer
    citations: List[Citation]
    # ROADMAP: Contradiction detection between sources.
    # Currently always empty ([]).  The intended v2 behaviour is to populate
    # this when evidence chunks from different authority tiers make conflicting
    # claims — e.g. Ofcom guidance interprets a provision differently from the
    # Explanatory Notes, or a Hansard speaker contradicts the statutory text.
    # Each entry would carry the two conflicting citations, a short
    # description of the disagreement, and the authority weights so the UI
    # can surface which source should be preferred.
    conflicts: List[Dict]
    evidence_pack: Optional[List[KBChunk]] = None
    retrieved_sources: Optional[List[KBChunk]] = None
    retrieval_debug: Optional[RetrievalDebug] = None
    kb_status: Optional[Dict] = None
    scope_classification: Optional[str] = None
    definition_mode: Optional[bool] = None
    status: str = "ok"
    message_user: Optional[str] = None
    suggestions: Optional[List[str]] = None
    closest_matches: Optional[List[KBChunk]] = None
    evidence_assessment: Optional[EvidenceAssessment] = None
    rewritten_question: Optional[str] = None
    # Parliament integration fields
    parliament_sources: Optional[List[Dict]] = None
    parliament_health: Optional[List[Dict]] = None
    source_freshness: Optional[str] = None
    synthesis_mode: Optional[str] = None  # "factual" or "strategic"


class RetrievedChunkDebug(BaseModel):
    document_id: str
    title: str
    category: str
    page: Optional[str]
    header: Optional[str]
    excerpt: str
    relevance_score: float
    bm25_score: float
    embedding_score: Optional[float]


class DebugRetrieveResponse(BaseModel):
    results: List[RetrievedChunkDebug]
    retrieval_mode: str
    kb_status: Dict


class KBStatus(BaseModel):
    last_refreshed: Optional[str]
    kb_loaded: bool
    total_chunks: int
    doc_counts_by_type: Dict[str, int]
    doc_counts_by_raw_type: Dict[str, int] = Field(default_factory=dict)
    chunk_counts_by_type: Dict[str, int] = Field(default_factory=dict)
    guidance_source_counts: Dict[str, int] = Field(default_factory=dict)
    validation_errors: List[str]
    config_limits: Dict[str, int]
    ingestion_summary: Dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_counts(
        cls,
        last_refreshed: Optional[datetime],
        total_chunks: int,
        doc_counts_by_type: Dict[str, int],
        validation_errors: List[str],
        config_limits: Dict[str, int],
        chunk_counts_by_type: Dict[str, int],
        guidance_source_counts: Dict[str, int],
        doc_counts_by_raw_type: Dict[str, int],
        ingestion_summary: Dict[str, int],
    ) -> "KBStatus":
        return cls(
            last_refreshed=last_refreshed.isoformat() if last_refreshed else None,
            kb_loaded=bool(last_refreshed),
            total_chunks=total_chunks,
            doc_counts_by_type=doc_counts_by_type,
            doc_counts_by_raw_type=doc_counts_by_raw_type,
            chunk_counts_by_type=chunk_counts_by_type,
            guidance_source_counts=guidance_source_counts,
            validation_errors=validation_errors,
            config_limits=config_limits,
            ingestion_summary=ingestion_summary,
        )
