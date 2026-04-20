import os
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

KB_DIR = Path("processed_knowledge_base")
LOG_DIR = Path("backend/logs")
LOG_FILE = LOG_DIR / "app.log"


def _get_float_env(var: str, default: str) -> float:
    value = os.getenv(var, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _get_int_env(var: str, default: int, min_value: int | None = None) -> int:
    value = os.getenv(var)
    try:
        int_value = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    if min_value is not None and int_value < min_value:
        return default
    return int_value

MAX_CHUNKS_TO_LLM = 25
MAX_CHARS_TO_LLM = 50000
MAX_EXCERPT_WORDS = 60
MAX_RETRIEVAL_CANDIDATES = 50
MAX_CHUNKS_PER_DOC = 1
MAX_CHUNKS_PER_SOURCE_TYPE = _get_int_env("MAX_CHUNKS_PER_SOURCE_TYPE", 5, min_value=1)
DEBUG_CANDIDATES_LIMIT = MAX_RETRIEVAL_CANDIDATES

# Survey-query retrieval widening (Brief 9 sub-job A / open-threads #83).
# When query_classifier.classify_query_kind() returns "survey", the pipeline
# swaps these caps in for the usual ones. Defaults adapted from iln_bot but
# tuned for DCMS's multi-source corpus (OSA KB chunks + Ofcom guidance +
# Hansard debates + Written Answers + Bills): per-source-type cap kept at
# 20 (vs iln_bot 30) so no single source type can monopolise a 40-chunk
# pack — preserves Parliament / Ofcom / Act breadth on broad survey
# queries like "main debates on online safety duties".
SURVEY_RETRIEVAL_TOP_K = _get_int_env("SURVEY_RETRIEVAL_TOP_K", 150, min_value=1)
SURVEY_MAX_CHUNKS_TO_LLM = _get_int_env("SURVEY_MAX_CHUNKS_TO_LLM", 40, min_value=1)
SURVEY_MAX_CHUNKS_PER_DOC = _get_int_env("SURVEY_MAX_CHUNKS_PER_DOC", 3, min_value=1)
SURVEY_MAX_CHUNKS_PER_SOURCE_TYPE = _get_int_env(
    "SURVEY_MAX_CHUNKS_PER_SOURCE_TYPE", 20, min_value=1
)
SURVEY_MAX_CHARS_TO_LLM = _get_int_env("SURVEY_MAX_CHARS_TO_LLM", 80000, min_value=1000)
MIN_SCORE_THRESHOLD = 0.15
MIN_RELEVANCE_SCORE = _get_float_env("MIN_RELEVANCE_SCORE", "0.25")
DEFINITION_DOC_TYPES = {"Act", "Explanatory Notes", "SI / Statutory Instrument"}
EVIDENCE_MIN_TOP_SCORE = _get_float_env("EVIDENCE_MIN_TOP_SCORE", "0.35")
EVIDENCE_MIN_COVERAGE = _get_float_env("EVIDENCE_MIN_COVERAGE", "0.35")
EVIDENCE_MIN_SEPARATION = _get_float_env("EVIDENCE_MIN_SEPARATION", "1.2")
EVIDENCE_TOP_K_FOR_COVERAGE = _get_int_env("EVIDENCE_TOP_K_FOR_COVERAGE", 3, min_value=1)

AUTHORITY_WEIGHTS: Dict[str, float] = {
    "Act": 10.0,
    "Act of Parliament": 10.0,
    "Primary legislation": 10.0,
    "Regulations": 8.0,
    "Ofcom Guidance": 7.0,
    "Explanatory Notes": 6.0,
    "Consultation": 5.0,
    "Impact Assessment": 5.0,
    "Hansard": 3.0,
    "Debate": 3.0,
    "Other": 1.0,
}

DEFAULT_FILTERS = {
    "primary_only": False,
    "include_guidance": True,
    "include_debates": True,
}

TOKEN_BUDGET_ESTIMATE_PER_CHAR = 0.25

LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").lower()
LLM_MAX_TOKENS = _get_int_env("LLM_MAX_TOKENS", 1024, min_value=128)
LLM_TEMPERATURE = _get_float_env("LLM_TEMPERATURE", "0.2")
LLM_TIMEOUT_SECONDS = _get_float_env("LLM_TIMEOUT_SECONDS", "30")
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-small")
EMBEDDINGS_BATCH_SIZE = _get_int_env("EMBEDDINGS_BATCH_SIZE", 50, min_value=1)
RETRIEVAL_MODE = os.getenv("RETRIEVAL_MODE", "hybrid").lower()

# Conversation / multi-turn settings
CONVERSATION_MAX_HISTORY_TURNS = _get_int_env("CONVERSATION_MAX_HISTORY_TURNS", 3, min_value=1)
CONVERSATION_MAX_HISTORY_CHARS = _get_int_env("CONVERSATION_MAX_HISTORY_CHARS", 10000, min_value=1000)

# Brief 9 sub-job B (open-threads #83): heuristic conversation-aware
# retrieval. When a follow-up is detected ("is that all?", "tell me
# more"), the retrieval-layer query is augmented with the previous user
# turn so the retriever keeps the topic. Distinct from the LLM-backed
# rewriter already in place (query_rewriter.rewrite_follow_up): this
# path runs with no LLM call and is cheap to keep on by default. The
# rewriter still runs after it when QUERY_REWRITE_ENABLED is true.
CONVERSATION_AWARE_RETRIEVAL_ENABLED = (
    os.getenv("CONVERSATION_AWARE_RETRIEVAL_ENABLED", "true").lower() == "true"
)

# Brief 9 sub-job C / Brief 11 (open-threads #83): corpus-match floor for
# the BM25 fallback counter. Retained only as a fallback for pathological
# function-word-only queries; the primary counter is content-token overlap
# (see CORPUS_MATCH_MIN_CONTENT_OVERLAP below).
CORPUS_MATCH_BM25_FLOOR = _get_float_env("CORPUS_MATCH_BM25_FLOOR", "0.0")

# Brief 11 (open-threads #83 follow-up): primary corpus_matches counter
# is content-token overlap. A chunk "matches" the query if its token set
# contains at least this many distinct content-bearing query tokens
# (length >= 4, non-numeric, not in the generic stopword set). Single-
# content-token queries automatically fall back to threshold=1. Set to
# 0 to disable content-overlap counting and revert to BM25-floor.
CORPUS_MATCH_MIN_CONTENT_OVERLAP = _get_int_env(
    "CORPUS_MATCH_MIN_CONTENT_OVERLAP", 2, min_value=0
)

# When evidence_pack / corpus_matches <= this ratio, the synthesis layer
# is told retrieval is the constraint (not corpus sparsity) so it can
# frame limitations honestly. 0.2 means a pack covering <=20% of the
# corpus-matching chunks is flagged as retrieval-limited.
RETRIEVAL_LIMITED_COVERAGE_THRESHOLD = _get_float_env(
    "RETRIEVAL_LIMITED_COVERAGE_THRESHOLD", "0.2"
)

# Honest-framing system-prompt rule, appended to the base synthesis
# prompt in llm_synthesis. Tunable via env so language can be re-worked
# without a code change (Brief 9 requirement).
HONEST_FRAMING_SYSTEM_RULE = os.getenv(
    "HONEST_FRAMING_SYSTEM_RULE",
    """\
9. The user message below may include a RETRIEVAL METADATA block with \
retrieval_coverage {requested, returned, pack_size, corpus_matches, \
kind, coverage_ratio, is_retrieval_limited}. When is_retrieval_limited \
is true (coverage_ratio is small and corpus_matches is large — the \
retriever surfaced a small slice of the corpus-matching chunks on this \
topic), frame any limitations as a retrieval-depth constraint, NOT \
corpus sparsity: "retrieval surfaced {pack_size} of ~{corpus_matches} \
matching chunks on this topic; a narrower or more specific query should \
surface fuller coverage." Do NOT say "the corpus contains little about \
X" in that case — the content is there, just not retrieved. When \
corpus_matches is itself small (single-digit or low tens), the corpus \
IS sparse on this topic; say so plainly. Factual queries (kind=factual) \
generally don't need this framing; survey queries (kind=survey) with \
is_retrieval_limited=true do.""",
)
DEFAULT_CORS_ALLOW_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

_LLM_REQUIRED_ENV_OPENAI = ["OPENAI_API_KEY"]
# For Anthropic, prefer ANTHROPIC_API_KEY_DCMS (product-scoped key for clean
# cost attribution at the billing layer); fall back to ANTHROPIC_API_KEY so
# existing local/Fly.io deployments keep working without a config flip.
_LLM_REQUIRED_ENV_ANTHROPIC = ["ANTHROPIC_API_KEY_DCMS", "ANTHROPIC_API_KEY"]
_EMBEDDINGS_REQUIRED_ENV = ["OPENAI_API_KEY"]


def anthropic_api_key() -> str | None:
    """Return the DCMS-scoped Anthropic key, falling back to the shared one."""
    return os.getenv("ANTHROPIC_API_KEY_DCMS") or os.getenv("ANTHROPIC_API_KEY")


def _llm_required_env() -> list[str]:
    if LLM_PROVIDER == "anthropic":
        return _LLM_REQUIRED_ENV_ANTHROPIC
    return _LLM_REQUIRED_ENV_OPENAI


def missing_llm_env() -> list[str]:
    # For Anthropic, the list is "one of these must be set", not "all set".
    if LLM_PROVIDER == "anthropic":
        return [] if anthropic_api_key() else [_LLM_REQUIRED_ENV_ANTHROPIC[0]]
    return [env for env in _llm_required_env() if not os.getenv(env)]


def llm_configured() -> bool:
    return not missing_llm_env()


def missing_embeddings_env() -> list[str]:
    return [env for env in _EMBEDDINGS_REQUIRED_ENV if not os.getenv(env)]


def embeddings_configured() -> bool:
    return not missing_embeddings_env()


def cors_allow_origins() -> list[str]:
    """
    Returns the allowed CORS origins, extending defaults with CORS_ALLOW_ORIGINS.

    The env var accepts a comma-separated list. Whitespace is stripped and empty
    entries are ignored. Defaults to the standard localhost Vite ports for dev.
    """
    origins_env = os.getenv("CORS_ALLOW_ORIGINS")
    origins = list(DEFAULT_CORS_ALLOW_ORIGINS)
    if not origins_env:
        return origins

    extras = [origin.strip() for origin in origins_env.split(",") if origin.strip()]
    for origin in extras:
        if origin not in origins:
            origins.append(origin)
    return origins
