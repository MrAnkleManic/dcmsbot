import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

from backend.logging_config import get_logger

logger = get_logger(__name__)

_GOLD_SUMMARIES_PATH = Path(__file__).resolve().parent.parent / "config" / "gold_summaries.json"


@lru_cache(maxsize=1)
def _load_gold_summaries() -> Dict[str, dict]:
    if not _GOLD_SUMMARIES_PATH.exists():
        raise FileNotFoundError(f"Gold summaries config not found at {_GOLD_SUMMARIES_PATH}")

    with _GOLD_SUMMARIES_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("Gold summaries config must be a JSON object keyed by summary id.")
    return data


def get_gold_summary_sentences(key: str) -> List[str]:
    data = _load_gold_summaries()
    if key not in data:
        raise KeyError(f"Gold summaries config missing key '{key}'.")

    entry = data[key]
    if not isinstance(entry, dict):
        raise ValueError(f"Gold summary '{key}' must be an object containing a 'sentences' list.")

    sentences = entry.get("sentences")
    if not isinstance(sentences, list) or not sentences or not all(isinstance(s, str) for s in sentences):
        raise ValueError(
            f"Gold summary '{key}' has invalid 'sentences'; expected a non-empty list of strings."
        )

    return list(sentences)
