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
DEBUG_CANDIDATES_LIMIT = MAX_RETRIEVAL_CANDIDATES
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
DEFAULT_CORS_ALLOW_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

_LLM_REQUIRED_ENV_OPENAI = ["OPENAI_API_KEY"]
_LLM_REQUIRED_ENV_ANTHROPIC = ["ANTHROPIC_API_KEY"]
_EMBEDDINGS_REQUIRED_ENV = ["OPENAI_API_KEY"]


def _llm_required_env() -> list[str]:
    if LLM_PROVIDER == "anthropic":
        return _LLM_REQUIRED_ENV_ANTHROPIC
    return _LLM_REQUIRED_ENV_OPENAI


def missing_llm_env() -> list[str]:
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
