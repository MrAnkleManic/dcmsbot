"""
Minimal smoke check to ensure retrieval surfaces illegal content references.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import config
from backend.core.loader import KnowledgeBase
from backend.core.models import QueryFilters
from backend.core.retriever import Retriever


def main() -> None:
    kb = KnowledgeBase()
    kb.load(config.KB_DIR)
    assert kb.chunks, "Knowledge base failed to load any chunks"

    retriever = Retriever(kb)
    retriever.build()

    results = retriever.retrieve("illegal content", QueryFilters(), top_k=10)
    assert results, "Retriever returned no results"

    top_texts = [r.chunk.chunk_text.lower() for r in results[:5]]
    contains_illegal = any("illegal content" in text for text in top_texts)
    mentions_section = any("section 59" in text or "priority illegal content" in text for text in top_texts)

    assert contains_illegal, "Top results did not mention illegal content"
    assert mentions_section, "Top results did not surface section 59 context"

    print("Smoke retrieval test passed: illegal content surfaced with section 59 context.")


if __name__ == "__main__":
    main()
