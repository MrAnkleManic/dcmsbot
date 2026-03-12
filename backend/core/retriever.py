import hashlib
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Tuple

import numpy as np
from rank_bm25 import BM25Okapi

from backend import config
from backend.core.doc_types import canonical_doc_type
from backend.core.loader import KnowledgeBase
from backend.core.models import KBChunk, QueryFilters
from backend.core.sections import chunk_section_number, parse_target_section
from backend.logging_config import get_logger

logger = get_logger(__name__)

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9']+")
_HYBRID_WEIGHT = 0.6
_SECTION_RERANK_WEIGHT = 0.55
_SECTION_REF_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bsection\s+(?P<number>[\dA-Za-z]+)(?P<subsection>\([^)]+\))?", re.IGNORECASE),
    re.compile(r"\bsec\.?\s+(?P<number>[\dA-Za-z]+)(?P<subsection>\([^)]+\))?", re.IGNORECASE),
    re.compile(r"\bs\.?\s*(?P<number>[\dA-Za-z]+)(?P<subsection>\([^)]+\))?", re.IGNORECASE),
    re.compile(r"§\s*(?P<number>[\dA-Za-z]+)(?P<subsection>\([^)]+\))?", re.IGNORECASE),
    re.compile(r"\barticle\s+(?P<number>[\dA-Za-z]+)(?P<subsection>\([^)]+\))?", re.IGNORECASE),
]
_SECTION_HEADING_PREFIX = r"(?:section heading:\s*)?"


def extract_section_ref(query: str) -> dict | None:
    section_number = parse_target_section(query)
    if section_number is None:
        return None
    for pattern in _SECTION_REF_PATTERNS:
        match = pattern.search(query)
        if not match:
            continue
        value = match.group("number")
        if not value:
            continue
        subsection = match.group("subsection")
        return {
            "kind": "section",
            "value": str(section_number),
            "subsection": subsection.strip() if subsection else None,
            "raw": match.group(0).strip(),
        }
    return None


def chunk_belongs_to_section(chunk_text: str, section_value: str) -> bool:
    value = str(section_value).strip()
    if not chunk_text or not value:
        return False

    escaped_value = re.escape(value)
    heading_patterns = [
        rf"^\s*{_SECTION_HEADING_PREFIX}section\s+{escaped_value}\b",
        rf"^\s*{_SECTION_HEADING_PREFIX}s\.?\s*{escaped_value}\b",
        rf"^\s*{_SECTION_HEADING_PREFIX}§\s*{escaped_value}\b",
        rf"^\s*{_SECTION_HEADING_PREFIX}article\s+{escaped_value}\b",
    ]
    pattern = re.compile("|".join(heading_patterns), re.IGNORECASE | re.MULTILINE)
    return bool(pattern.search(chunk_text))


def chunk_matches_section(chunk: KBChunk, section_number: str) -> bool:
    """
    Backwards-compatible alias for chunk_belongs_to_section.
    """
    haystack = _section_match_text(chunk)
    return chunk_belongs_to_section(haystack, section_number)


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_PATTERN.findall(text)]


# text-embedding-3-small has an 8191-token limit per text.
# Legislative text tokenises at roughly 1.4–2 chars/token (numbers, section
# refs, parenthetical sub-clauses all produce short tokens).  We cap at
# 10,000 chars (~5,000–7,000 tokens) to stay safely within the per-text limit.
_MAX_EMBED_CHARS = 10_000


def _chunk_index_text(chunk: KBChunk) -> str:
    if chunk.header:
        text = f"{chunk.header}\n{chunk.chunk_text}"
    else:
        text = chunk.chunk_text
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS]
    return text


def section_match_text(chunk: KBChunk) -> str:
    parts = [chunk.header or "", chunk.location_pointer or "", chunk.chunk_text or ""]
    return "\n".join(part for part in parts if part)


# Backwards-compatible alias: historically imported with an underscore prefix.
_section_match_text = section_match_text


def _lexical_overlap_score(query: str, text: str) -> float:
    query_tokens = {t for t in _tokenize(query) if len(t) > 2}
    text_tokens = {t for t in _tokenize(text) if len(t) > 2}
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = len(query_tokens & text_tokens)
    return overlap / max(len(query_tokens), 1)


@dataclass
class RetrievedChunk:
    chunk: KBChunk
    final_score: float
    bm25_score: float
    embedding_score: float | None = None


class Retriever:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.model: BM25Okapi | None = None
        self._tokenized_corpus: List[List[str]] = []
        self._embeddings: List[List[float]] | None = None
        self.index_ready: bool = False
        self.retrieval_mode: str = config.RETRIEVAL_MODE
        self._last_context: dict = {}

    def build(self) -> None:
        self._tokenized_corpus = [_tokenize(_chunk_index_text(c)) for c in self.kb.chunks]
        if self._tokenized_corpus:
            self.model = BM25Okapi(self._tokenized_corpus)
        else:
            self.model = None
        self.index_ready = bool(self.model)
        self._embeddings = self._build_embeddings() if config.embeddings_configured() else None
        logger.info(
            "Retriever index built",
            extra={
                "chunks": len(self._tokenized_corpus),
                "embeddings": bool(self._embeddings),
                "mode": self.effective_mode(),
            },
        )

    @staticmethod
    def _embeddings_cache_key(texts: List[str], model: str) -> str:
        """Deterministic hash of chunk texts + model name for cache invalidation."""
        hasher = hashlib.sha256()
        hasher.update(model.encode())
        for text in texts:
            hasher.update(text.encode())
        return hasher.hexdigest()[:16]

    @staticmethod
    def _committed_cache_path() -> Path:
        """Pre-generated cache committed to git for instant first boot."""
        return Path(config.KB_DIR) / "embeddings_cache.json"

    @staticmethod
    def _runtime_cache_path(cache_key: str) -> Path:
        """Per-session cache in .cache/ (gitignored) for warm restarts."""
        cache_dir = Path(config.KB_DIR) / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"embeddings_{cache_key}.json"

    def _load_cached_embeddings(self, cache_path: Path) -> List[List[float]] | None:
        if not cache_path.exists():
            return None
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            embeddings = data.get("embeddings")
            if embeddings and len(embeddings) == len(self.kb.chunks):
                logger.info(
                    "Loaded embeddings from cache",
                    extra={"path": str(cache_path), "chunks": len(embeddings)},
                )
                return embeddings
            logger.info(
                "Cache size mismatch, will regenerate",
                extra={"cached": len(embeddings) if embeddings else 0, "expected": len(self.kb.chunks)},
            )
            return None
        except Exception:  # noqa: BLE001
            logger.warning("Failed to read embeddings cache, will regenerate", extra={"path": str(cache_path)})
            return None

    def _save_cached_embeddings(self, cache_path: Path, embeddings: List[List[float]], cache_key: str) -> None:
        try:
            with cache_path.open("w", encoding="utf-8") as f:
                json.dump({"cache_key": cache_key, "model": config.EMBEDDINGS_MODEL, "chunks": len(embeddings), "embeddings": embeddings}, f)
            logger.info("Saved embeddings cache", extra={"path": str(cache_path), "chunks": len(embeddings)})
        except Exception:  # noqa: BLE001
            logger.warning("Failed to write embeddings cache", extra={"path": str(cache_path)})

    def _build_embeddings(self) -> List[List[float]] | None:
        if not self.kb.chunks:
            return None

        texts = [_chunk_index_text(c) for c in self.kb.chunks]
        cache_key = self._embeddings_cache_key(texts, config.EMBEDDINGS_MODEL)

        # 1. Try the pre-committed cache (instant first boot for demos)
        committed = self._committed_cache_path()
        cached = self._load_cached_embeddings(committed)
        if cached is not None:
            return cached

        # 2. Try the runtime cache in .cache/ (warm restarts after KB changes)
        runtime = self._runtime_cache_path(cache_key)
        cached = self._load_cached_embeddings(runtime)
        if cached is not None:
            return cached

        # 3. Generate fresh embeddings via API (cold start with no cache)
        try:
            from openai import OpenAI

            client = OpenAI()
            embeddings: List[List[float]] = []

            # Token-aware batching: the embedding API has a per-request token
            # limit (8191 for text-embedding-3-small).  Legislative text
            # tokenises at ~2 chars/token, so 14K chars ≈ 7K tokens.
            max_batch_chars = 14_000
            batch: List[str] = []
            batch_chars = 0

            for text in texts:
                text_len = len(text)
                if batch and batch_chars + text_len > max_batch_chars:
                    response = client.embeddings.create(model=config.EMBEDDINGS_MODEL, input=batch)
                    embeddings.extend([item.embedding for item in response.data])
                    batch = []
                    batch_chars = 0
                batch.append(text)
                batch_chars += text_len

            if batch:
                response = client.embeddings.create(model=config.EMBEDDINGS_MODEL, input=batch)
                embeddings.extend([item.embedding for item in response.data])

            # Persist to runtime cache for next restart
            self._save_cached_embeddings(runtime, embeddings, cache_key)
            return embeddings
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to build embeddings index", extra={"error": str(exc)})
            return None

    def _filter_chunks(
        self,
        filters: QueryFilters,
        allowed_doc_types: set[str] | None = None,
        override_filters: bool = False,
    ) -> Tuple[List[KBChunk], List[int]]:
        filtered: List[KBChunk] = []
        indices: List[int] = []
        allowed = {doc_type.lower() for doc_type in allowed_doc_types} if allowed_doc_types else None

        # New category-based filtering: if enabled_categories is set, use it
        enabled_set = (
            {cat.lower() for cat in filters.enabled_categories}
            if filters.enabled_categories is not None
            else None
        )

        for idx, chunk in enumerate(self.kb.chunks):
            doc_type = canonical_doc_type(chunk.source_type)
            if allowed and doc_type.lower() not in allowed:
                continue
            if override_filters and allowed:
                filtered.append(chunk)
                indices.append(idx)
                continue

            # If enabled_categories is provided, use it exclusively
            if enabled_set is not None:
                if doc_type.lower() not in enabled_set:
                    continue
            else:
                # Legacy filter logic
                if filters.primary_only and doc_type != "Act":
                    continue
                if not filters.include_guidance and doc_type == "Regulator Guidance":
                    continue
                if not filters.include_debates and doc_type == "Debates / Hansard":
                    continue

            filtered.append(chunk)
            indices.append(idx)
        return filtered, indices

    def _embed_query(self, query: str) -> np.ndarray | None:
        if not self._embeddings:
            return None
        try:
            from openai import OpenAI

            client = OpenAI()
            response = client.embeddings.create(model=config.EMBEDDINGS_MODEL, input=[query])
            return np.array(response.data[0].embedding, dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to embed query", extra={"error": str(exc)})
            return None

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    def effective_mode(self) -> str:
        if self.retrieval_mode == "embeddings" and not self._embeddings:
            return "bm25"
        if self.retrieval_mode == "hybrid" and not self._embeddings:
            return "bm25"
        if self.retrieval_mode in {"bm25", "hybrid", "embeddings"}:
            return self.retrieval_mode
        return "bm25"

    def retrieve(
        self,
        query: str,
        filters: QueryFilters,
        top_k: int | None = None,
        allowed_doc_types: set[str] | None = None,
        override_filters: bool = False,
    ) -> List[RetrievedChunk]:
        self._last_context = {"section_value": None, "section_match": False}
        if not self.model:
            return []
        filtered_chunks, indices = self._filter_chunks(
            filters, allowed_doc_types=allowed_doc_types, override_filters=override_filters
        )
        if not filtered_chunks:
            return []

        target_section = parse_target_section(query)

        tokenized_query = _tokenize(query)
        bm25_scores_all = self.model.get_scores(tokenized_query)
        filtered_bm25 = [bm25_scores_all[idx] for idx in indices]
        bm25_max = max(filtered_bm25) if filtered_bm25 else 1.0

        query_embedding = None
        if self.effective_mode() in {"hybrid", "embeddings"}:
            query_embedding = self._embed_query(query)

        scored: List[RetrievedChunk] = []
        for pos, chunk_idx in enumerate(indices):
            chunk = filtered_chunks[pos]
            bm25_score = filtered_bm25[pos]
            bm25_norm = bm25_score / bm25_max if bm25_max else 0.0
            embedding_score = None
            embedding_norm = 0.0
            if query_embedding is not None and self._embeddings:
                chunk_vec = np.array(self._embeddings[chunk_idx], dtype=np.float32)
                embedding_score = self._cosine_similarity(chunk_vec, query_embedding)
                embedding_norm = (embedding_score + 1) / 2  # scale to 0..1

            if self.effective_mode() == "embeddings" and embedding_score is not None:
                combined = embedding_norm
            elif self.effective_mode() == "hybrid" and embedding_score is not None:
                combined = (_HYBRID_WEIGHT * bm25_norm) + ((1 - _HYBRID_WEIGHT) * embedding_norm)
            else:
                combined = bm25_norm

            weight_multiplier = chunk.authority_weight
            final_score = combined * (1 + math.log1p(weight_multiplier))

            candidate = RetrievedChunk(
                chunk=chunk,
                final_score=final_score,
                bm25_score=bm25_score,
                embedding_score=embedding_score,
            )

            scored.append(candidate)

        scored = _stable_sort_retrieved(scored)

        deduped: List[RetrievedChunk] = []
        seen_text_hashes = set()
        for cand in scored:
            normalized = " ".join(cand.chunk.chunk_text.split()).lower()
            if normalized in seen_text_hashes:
                continue
            seen_text_hashes.add(normalized)
            deduped.append(cand)

        limit = top_k or config.MAX_RETRIEVAL_CANDIDATES
        base_candidates = deduped[:limit]

        if target_section is not None:
            metadata_matches = [
                cand for cand in deduped if chunk_section_number(cand.chunk) == target_section
            ]
            heading_matches = [
                cand
                for cand in deduped
                if chunk_belongs_to_section(_section_match_text(cand.chunk), str(target_section))
            ]

            match_pool = metadata_matches or heading_matches or deduped
            match_type = (
                "metadata" if metadata_matches else "heading" if heading_matches else "fallback"
            )

            if metadata_matches or heading_matches:
                match_pool = self._rerank_section_candidates(match_pool, query)
            trimmed = match_pool[:limit]

            self._last_context = {
                "section_value": target_section,
                "section_match": bool(metadata_matches or heading_matches),
                "section_lock": f"s.{target_section}",
                "pre_filter": len(base_candidates),
                "post_filter": len(metadata_matches or heading_matches),
                "match_type": match_type,
            }
            logger.info(
                "Section lock applied",
                extra={
                    "section_value": target_section,
                    "candidates_pre_filter": len(base_candidates),
                    "candidates_post_filter": len(metadata_matches or heading_matches),
                    "match_type": match_type,
                    "top_chunk_ids": [c.chunk.chunk_id for c in trimmed[:5]],
                },
            )
            return trimmed

        self._last_context = {
            "section_value": None,
            "section_match": False,
            "section_lock": "off",
            "match_type": "none",
        }
        logger.info(
            "Retrieved candidates",
            extra={
                "query": query,
                "retrieved": len(base_candidates),
                "filters": filters.dict(),
                "mode": self.effective_mode(),
            },
        )
        return base_candidates

    def _rerank_section_candidates(
        self, candidates: List[RetrievedChunk], query: str
    ) -> List[RetrievedChunk]:
        if not candidates:
            return candidates

        original_max = max((c.final_score for c in candidates), default=1.0)
        lexical_scores = [
            _lexical_overlap_score(query, _chunk_index_text(c.chunk)) for c in candidates
        ]
        lexical_max = max(lexical_scores) if lexical_scores else 1.0

        reranked: List[RetrievedChunk] = []
        for cand, lexical in zip(candidates, lexical_scores):
            lexical_norm = lexical / lexical_max if lexical_max else 0.0
            original_norm = cand.final_score / original_max if original_max else 0.0
            combined = (_SECTION_RERANK_WEIGHT * lexical_norm) + (
                (1 - _SECTION_RERANK_WEIGHT) * original_norm
            )
            combined = max(combined, 1e-6)
            reranked.append(replace(cand, final_score=combined))

        reranked = _stable_sort_retrieved(reranked)
        return reranked

    def status(self) -> dict:
        return {
            "retrieval_mode": self.effective_mode(),
            "embeddings_ready": bool(self._embeddings),
            "index_ready": self.index_ready,
        }

    def last_context(self) -> dict:
        return self._last_context


def _stable_sort_retrieved(candidates: List[RetrievedChunk]) -> List[RetrievedChunk]:
    return sorted(
        candidates,
        key=lambda c: (-c.final_score, c.chunk.doc_id, c.chunk.chunk_id),
    )
