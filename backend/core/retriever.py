import hashlib
import json
import math
import os
import re
import threading
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

import numpy as np
from nltk.stem.porter import PorterStemmer
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

# Brief 12 (iln_bot@b8dd70a): PorterStemmer collapses morphological
# variants so BM25 treats "murdered" / "murders" / "murdering" as the
# same token. DCMS equivalent: a user asking "were there any fines
# imposed" gets chunks that say "fined" / "fining"; "enforcement
# actions" matches chunks that say "enforced"; plural/past-tense drift
# used to silently zero out BM25 for these shapes.
#
# Porter over Snowball: more conservative, less prone to false-positive
# conflations like archive/archiv (Snowball). If a future query turns
# up a real plural/past-tense miss that Porter doesn't catch, revisit.
#
# Disk-cache invalidation note: DCMS has a disk-backed embedding cache
# (committed embeddings_cache.npy + runtime .cache/*.npy, introduced in
# Brief 6 backport 6dffec5). The cache key is sha256(chunk_text concat +
# embedding model) — chunk text and OpenAI's embedding tokenisation are
# unaffected by our local BM25 stemmer swap, so the embedding cache does
# NOT need invalidation. BM25 itself has no disk cache in this codebase
# (the index is rebuilt in memory on every startup from self.kb.chunks)
# so swapping the tokeniser auto-invalidates the BM25 index on next boot.
# No cache files to delete.
_STEMMER = PorterStemmer()

# Porter is pure-Python and ~1us per call; on DCMS's 28,548-chunk corpus
# that would add ~20s to index build. Token repetition is heavy ("the",
# "of", "section", regulatory terms that recur across Ofcom codes and
# Act provisions), so a plain dict cache cuts the work order-of-magnitude
# without changing semantics. Cache is process-local and grows with
# corpus vocabulary — bounded by English + regulatory tokens, so memory
# is trivial.
_STEM_CACHE: dict[str, str] = {}


def _normalise_token(tok: str) -> str:
    """Lowercase, strip possessive apostrophe-s, then stem.

    Possessive stripping happens pre-stem because Porter is undefined on
    embedded punctuation — "ofcom's" left intact stems to a different
    token than "ofcom". Numeric tokens bypass the stemmer so year /
    section tokens like "2023" or "64" survive unchanged.
    """
    tok = tok.lower()
    if tok.endswith("'s"):
        tok = tok[:-2]
    elif tok.endswith("'"):
        tok = tok[:-1]
    if not tok:
        return ""
    if tok.isdigit():
        return tok
    cached = _STEM_CACHE.get(tok)
    if cached is not None:
        return cached
    stemmed = _STEMMER.stem(tok)
    _STEM_CACHE[tok] = stemmed
    return stemmed

# Brief 11 (open-threads #83 follow-up): discriminative corpus-match counter.
# The Brief 9 implementation counted any chunk with BM25 > 0 — on the DCMS
# corpus (mixed Act / Ofcom guidance / Hansard / Written Answers) that
# would surface nearly every chunk for broad scaffolding tokens like
# "section", "the", "online", "safety". The ratio is useless for honest-
# framing ("5 of ~28,000 matching chunks" is not a meaningful denominator).
#
# Replacement: extract content tokens from the query (length >= 4, not
# purely numeric, not in a compact stopword set of generic question /
# regulatory / scaffolding words), then count chunks whose token sets
# contain >=2 of them (threshold drops to >=1 when the query has only
# one content token).
#
# DCMS adaptation vs iln_bot: the ILN-corpus-specific nouns ("iln",
# "illustrated", "newspaper", "article", "story") are dropped — they
# would be topic words in a DCMS context. Scaffolding / request verbs
# / question words / common short prepositions are kept because they
# are cross-corpus generic.
_CORPUS_MATCH_STOPWORDS = frozenset({
    # Question scaffolding
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "does", "do", "did", "done", "can", "could", "would", "should", "will",
    "were", "was", "been", "have", "has", "had", "are", "is", "be",
    # Conjunctions / prepositions / determiners >=4 chars
    "with", "from", "into", "onto", "over", "about", "during", "within",
    "this", "that", "these", "those", "them", "they", "their", "there",
    "here", "also", "each", "every", "some", "many", "such", "much",
    "more", "most", "less", "least", "only", "else", "like", "than",
    "then", "your", "mine", "ours", "hers", "yourselves",
    # Generic reporting / coverage words — they describe how something
    # is referenced, not the topic itself.
    "report", "reports", "reported", "reporting", "mention", "mentioned",
    "mentions", "cover", "covered", "coverage", "covering", "happen",
    "happened", "said", "saying", "discuss", "discussed", "discussing",
    # Generic editorial adjectives (don't narrow the corpus)
    "recent", "latest", "other", "various", "please",
    # Request verbs / prompt shaping — the user asking us to "draft a
    # narrative" or "tell me about" isn't describing the TOPIC, they're
    # describing the desired output shape.
    "draft", "narrative", "write", "writing", "given", "tell", "telling",
    "give", "show", "produce", "provide", "create", "compose", "compile",
    "list", "summary", "summarise", "summarize", "describe", "description",
    "explain", "explanation", "outline", "overview",
})


# Brief 12: with stemming in _tokenize the corpus-matches filter sees
# stemmed tokens, so the stopword set has to be compared stem-to-stem
# too. Pre-stem the canonical set once at module load so lookups stay
# O(1) and _CORPUS_MATCH_STOPWORDS remains the human-readable source of
# truth (Brief 11 tests still pin it in surface form).
_STEMMED_STOPWORDS: frozenset[str] = frozenset(
    _normalise_token(w) for w in _CORPUS_MATCH_STOPWORDS
)


def _extract_content_tokens(tokens: list[str]) -> list[str]:
    """Filter query tokens down to content-bearing ones for corpus_matches.

    Expects *tokens* to already be normalised via _tokenize (lowercased,
    possessive-stripped, and Porter-stemmed). Excludes short tokens
    (< 4 chars after stemming), purely numeric tokens, and generic
    scaffolding from the stemmed stopword set. Preserves order and
    collapses duplicates.
    """
    seen: set[str] = set()
    content: list[str] = []
    for tok in tokens:
        if tok in seen:
            continue
        if len(tok) < 4:
            continue
        if tok.isdigit():
            continue
        if tok in _STEMMED_STOPWORDS:
            continue
        seen.add(tok)
        content.append(tok)
    return content


def _count_content_matches(
    content_tokens: list[str],
    chunk_token_sets: list[frozenset[str]],
    filtered_indices: list[int],
    threshold: int,
) -> int:
    """Count filtered chunks containing >=*threshold* of *content_tokens*."""
    if not content_tokens or not filtered_indices:
        return 0
    needles = set(content_tokens)
    hits = 0
    for idx in filtered_indices:
        if sum(1 for tok in needles if tok in chunk_token_sets[idx]) >= threshold:
            hits += 1
    return hits


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
    tokens: List[str] = []
    for raw in _TOKEN_PATTERN.findall(text):
        tok = _normalise_token(raw)
        if tok:
            tokens.append(tok)
    return tokens


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
        # Brief 11: per-chunk token set, parallel to _tokenized_corpus, used
        # by the discriminative corpus_matches counter. Built once at index
        # build time; set-membership is O(1) per lookup.
        self._chunk_token_sets: List[frozenset[str]] = []
        self._embeddings: np.ndarray | None = None
        self._embeddings_loading: bool = False
        self._embeddings_lock = threading.Lock()
        self._embeddings_info: dict = {"chunk_count": 0, "dim": 0, "rebuilt_at": None}
        self.index_ready: bool = False
        self.retrieval_mode: str = config.RETRIEVAL_MODE
        self._last_context: dict = {}

    def build(self) -> None:
        self._tokenized_corpus = [_tokenize(_chunk_index_text(c)) for c in self.kb.chunks]
        # Brief 11: keep per-chunk token sets in sync with the tokenized
        # corpus. Using frozenset so callers cannot mutate in place.
        self._chunk_token_sets = [frozenset(toks) for toks in self._tokenized_corpus]
        if self._tokenized_corpus:
            self.model = BM25Okapi(self._tokenized_corpus)
        else:
            self.model = None
        # Invalidate the previous embedding matrix — after a /refresh the
        # loader may have added, removed, or reordered chunks, so the old
        # matrix is no longer aligned with self.kb.chunks. Callers that
        # need embeddings ready immediately (e.g. /refresh) must call
        # rebuild_embeddings(); otherwise the next retrieve() will rebuild
        # lazily via _ensure_embeddings.
        self._embeddings = None
        self._embeddings_info = {"chunk_count": 0, "dim": 0, "rebuilt_at": None}
        self.index_ready = bool(self.model)
        logger.info(
            "Retriever index built (embeddings deferred)",
            extra={
                "chunks": len(self._tokenized_corpus),
                "mode": self.effective_mode(),
            },
        )

    def rebuild_embeddings(self) -> dict:
        """Eagerly (re)build the embedding matrix.

        Chosen over lazy invalidation for /refresh so the response can report
        the new matrix shape and the first post-refresh query is not penalised
        by cold-start embedding generation.

        Safe to call when embeddings are not configured (no OpenAI key) — the
        matrix stays None and the info dict reports zero chunks.
        """
        self._ensure_embeddings()
        if self._embeddings is not None:
            shape = self._embeddings.shape
            self._embeddings_info = {
                "chunk_count": int(shape[0]),
                "dim": int(shape[1]) if len(shape) > 1 else 0,
                "rebuilt_at": datetime.now(timezone.utc).isoformat(),
            }
        else:
            self._embeddings_info = {
                "chunk_count": 0,
                "dim": 0,
                "rebuilt_at": datetime.now(timezone.utc).isoformat(),
            }
        logger.info("Embeddings rebuilt", extra=self._embeddings_info)
        return dict(self._embeddings_info)

    def _ensure_embeddings(self) -> None:
        """Load embeddings on first use (lazy loading)."""
        if self._embeddings is not None or not config.embeddings_configured():
            return
        with self._embeddings_lock:
            if self._embeddings is not None:
                return
            self._embeddings_loading = True
            try:
                self._embeddings = self._build_embeddings()
            finally:
                self._embeddings_loading = False
            logger.info(
                "Embeddings loaded lazily",
                extra={"embeddings": self._embeddings is not None, "mode": self.effective_mode()},
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
    def _committed_npy_path() -> Path:
        """Pre-generated numpy cache for instant first boot (~167MB vs ~3.8GB JSON)."""
        return Path(config.KB_DIR) / "embeddings_cache.npy"

    @staticmethod
    def _committed_cache_path() -> Path:
        """Legacy JSON cache (fallback if numpy not available)."""
        return Path(config.KB_DIR) / "embeddings_cache.json"

    @staticmethod
    def _runtime_cache_path(cache_key: str) -> Path:
        """Per-session cache in .cache/ (gitignored) for warm restarts."""
        cache_dir = Path(config.KB_DIR) / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"embeddings_{cache_key}.npy"

    def _load_npy_cache(self, npy_path: Path, *, allow_mmap: bool = False) -> np.ndarray | None:
        """Load embeddings from numpy binary format (memory-efficient).

        When *allow_mmap* is True the file is memory-mapped read-only so the OS
        pages data in on demand instead of copying the full array into the
        Python heap.  This keeps RSS well below the 4 GB machine limit.
        """
        if not npy_path.exists():
            return None
        try:
            arr = np.load(npy_path, mmap_mode="r" if allow_mmap else None)
            if arr.shape[0] == len(self.kb.chunks):
                logger.info(
                    "Loaded embeddings from numpy cache",
                    extra={
                        "path": str(npy_path),
                        "shape": list(arr.shape),
                        "dtype": str(arr.dtype),
                        "mmap": allow_mmap,
                    },
                )
                return arr.astype(np.float32) if arr.dtype != np.float32 else arr
            logger.info(
                "Numpy cache size mismatch, will regenerate",
                extra={"cached": arr.shape[0], "expected": len(self.kb.chunks)},
            )
            return None
        except Exception:  # noqa: BLE001
            logger.warning("Failed to read numpy embeddings cache", extra={"path": str(npy_path)})
            return None

    def _load_json_cache(self, cache_path: Path) -> np.ndarray | None:
        """Fallback: load from JSON and convert to numpy array."""
        if not cache_path.exists():
            return None
        try:
            with cache_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            embeddings = data.get("embeddings")
            if embeddings and len(embeddings) == len(self.kb.chunks):
                arr = np.array(embeddings, dtype=np.float32)
                logger.info(
                    "Loaded embeddings from JSON cache (consider converting to numpy)",
                    extra={"path": str(cache_path), "chunks": len(embeddings)},
                )
                return arr
            logger.info(
                "JSON cache size mismatch, will regenerate",
                extra={"cached": len(embeddings) if embeddings else 0, "expected": len(self.kb.chunks)},
            )
            return None
        except Exception:  # noqa: BLE001
            logger.warning("Failed to read JSON embeddings cache", extra={"path": str(cache_path)})
            return None

    def _save_npy_cache(self, npy_path: Path, embeddings: np.ndarray) -> None:
        # Write to a sibling temp file then rename into place. os.replace is
        # atomic on POSIX, so concurrent readers (mmap) never see a partial
        # file during a rebuild.
        tmp_path = npy_path.with_name(f"{npy_path.name}.tmp.{os.getpid()}")
        try:
            with tmp_path.open("wb") as fh:
                np.save(fh, embeddings)
            os.replace(tmp_path, npy_path)
            logger.info(
                "Saved numpy embeddings cache",
                extra={"path": str(npy_path), "shape": list(embeddings.shape)},
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to write numpy embeddings cache", extra={"path": str(npy_path)})
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def _build_embeddings(self) -> np.ndarray | None:
        if not self.kb.chunks:
            return None

        texts = [_chunk_index_text(c) for c in self.kb.chunks]
        cache_key = self._embeddings_cache_key(texts, config.EMBEDDINGS_MODEL)

        # 1. Try pre-committed numpy cache with mmap (preferred — keeps RSS low)
        npy_committed = self._committed_npy_path()
        cached = self._load_npy_cache(npy_committed, allow_mmap=True)
        if cached is not None:
            return cached

        # 2. Try runtime numpy cache (written by a previous cold-start)
        runtime = self._runtime_cache_path(cache_key)
        cached = self._load_npy_cache(runtime, allow_mmap=True)
        if cached is not None:
            return cached

        # NOTE: Legacy JSON fallback removed — loading the 932 MB JSON into
        # Python float objects requires ~3.8 GB of RAM and OOM-kills on a
        # 4 GB machine.  Only numpy (.npy) caches are supported.

        # 3. Generate fresh embeddings via API (cold start with no cache)
        try:
            from openai import OpenAI

            client = OpenAI()
            all_embeddings: List[List[float]] = []

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
                    all_embeddings.extend([item.embedding for item in response.data])
                    batch = []
                    batch_chars = 0
                batch.append(text)
                batch_chars += text_len

            if batch:
                response = client.embeddings.create(model=config.EMBEDDINGS_MODEL, input=batch)
                all_embeddings.extend([item.embedding for item in response.data])

            arr = np.array(all_embeddings, dtype=np.float32)
            # Persist as numpy for next restart
            self._save_npy_cache(runtime, arr)
            return arr
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
        if self._embeddings is None:
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
        if self.retrieval_mode == "embeddings" and self._embeddings is None:
            return "bm25"
        if self.retrieval_mode == "hybrid" and self._embeddings is None:
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

        # Lazy-load embeddings on first retrieval request
        self._ensure_embeddings()

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

        # Discriminative corpus-matches counter (Brief 11 / open-threads #83
        # follow-up). Extract content-bearing tokens from the query (>=4
        # chars, non-numeric, non-stopword) then count filtered chunks that
        # contain >=CORPUS_MATCH_MIN_CONTENT_OVERLAP of them. For single-
        # content-token queries the threshold drops to 1.
        #
        # Legacy BM25-floor behaviour is kept as a fallback when the query
        # has zero content tokens (pathological: a short function-word-only
        # query). Also preserved when CORPUS_MATCH_MIN_CONTENT_OVERLAP is
        # explicitly set to 0 — operators who want the old counter back
        # can flip that env var.
        content_tokens = _extract_content_tokens(tokenized_query)
        threshold_cfg = getattr(config, "CORPUS_MATCH_MIN_CONTENT_OVERLAP", 2)
        if content_tokens and threshold_cfg >= 1:
            # Threshold sizing: use ceil(N/2) so the denominator counts
            # chunks that mention at least half of the topic tokens. This
            # keeps short editorial queries generous (1 or 2 content words
            # → threshold 1, i.e. union) and scales up for topic-heavy
            # queries (3-4 tokens → threshold 2) without demanding that
            # every token appear in every chunk. Capped by threshold_cfg
            # so operators can tighten (env-var raise) but never exceed
            # the natural ceiling of the token count.
            natural_threshold = max(1, (len(content_tokens) + 1) // 2)
            threshold = min(threshold_cfg, natural_threshold, len(content_tokens))
            corpus_matches = _count_content_matches(
                content_tokens, self._chunk_token_sets, indices, threshold=threshold
            )
            corpus_match_method = f"content-overlap>={threshold}"
        else:
            floor = getattr(config, "CORPUS_MATCH_BM25_FLOOR", 0.0)
            corpus_matches = sum(1 for s in filtered_bm25 if s > floor)
            corpus_match_method = f"bm25>{floor}"

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
            if query_embedding is not None and self._embeddings is not None:
                chunk_vec = self._embeddings[chunk_idx]
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
                "corpus_matches": corpus_matches,
                "corpus_match_method": corpus_match_method,
                "content_tokens": content_tokens,
                "requested_top_k": limit,
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
            "corpus_matches": corpus_matches,
            "corpus_match_method": corpus_match_method,
            "content_tokens": content_tokens,
            "requested_top_k": limit,
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
            "embeddings_ready": self._embeddings is not None,
            "embeddings_loading": self._embeddings_loading,
            "embeddings_info": dict(self._embeddings_info),
            "index_ready": self.index_ready,
        }

    def last_context(self) -> dict:
        return self._last_context


def _stable_sort_retrieved(candidates: List[RetrievedChunk]) -> List[RetrievedChunk]:
    return sorted(
        candidates,
        key=lambda c: (-c.final_score, c.chunk.doc_id, c.chunk.chunk_id),
    )
