"""Query-type classification for retrieval routing.

Distinguishes survey/overview queries ("main debates on online safety
duties", "all the Ofcom guidance on illegal content") from factual-
pointed ones ("what does Section 64 say?", "what did the minister answer
on 2024-03-14?"). Survey queries need recall — the evidence-pack builder
widens its caps. Factual-pointed queries keep the current precision-
optimised behaviour.

Heuristic first: a lowercase-normalised cue match. If any cue phrase is
present, the query is routed as survey. The phrase list is configurable
via `SURVEY_QUERY_CUES` (comma-separated env var). A classifier model
can replace this later without touching the callers.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Literal

# Default cue phrases. Each is lowercased; matching is a whole-word-ish
# substring check on the lowercased question. Keep the list conservative
# but generous — false positives widen the pack (safe); false negatives
# leave the current precision path (status quo).
#
# Adapted from iln_bot@0eaed1b for DCMS's OSA / Hansard / Ofcom domain.
# Brief 11 cue extensions (editorial / curation shapes — "top N",
# "narrative of", "were there any") are kept; newspaper-specific cues
# ("what did the ILN cover") are replaced with Parliament / regulator
# equivalents ("main debates", "what did ministers say", "range of
# guidance").
_DEFAULT_SURVEY_CUES: tuple[str, ...] = (
    "key events",
    "everything about",
    "everything on",
    "list of",
    "overview",
    "all the",
    "tell me about",
    "tell me everything",
    "what happened to",
    "what happened in",
    "what can you tell me about",
    "give me an overview",
    "summarise",
    "summarize",
    "broad",
    "range of",
    "various",
    "many",
    # Editorial / curation / survey shapes (Brief 11)
    "were there any",
    "narrative of",
    "draft a narrative",
    "actions during",
    "write a narrative",
    # DCMS-domain survey shapes — kept deliberately narrow. Cues that
    # were too ambiguous ("what did the minister say", "what has ofcom
    # said", "across the act", "under the act") matched factual-pointed
    # queries and were dropped; curation intent is better captured by
    # plurality / breadth markers ("main X", "range of X") plus the
    # regex curation patterns below.
    "main debates",
    "key debates",
    "main arguments",
    "key arguments",
    "main provisions",
    "key provisions",
    "main duties",
    "key duties",
    "range of duties",
    "range of guidance",
    "all duties",
    "all guidance",
)

# Open-question shapes that imply breadth. Regex, matched after lowercasing.
# These are deliberately narrow — they fire for "what topics did X cover"
# not for "what does Section 64 say on record-keeping".
_SURVEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bwhat topics\b"),
    re.compile(r"\bwhich events\b"),
    re.compile(r"\bwhat events\b"),
    re.compile(r"\ball\s+(events|topics|debates|duties|provisions|mentions|references|guidance)\b"),
    # Brief 11 — editorial curation patterns:
    # "Top 5 main debates" / "Top 10 notable provisions" — a curated
    # selection request, not quantitative analytics. Pairs with the
    # query_guard change that stops refusing "top N" when kind=survey.
    re.compile(r"\btop\s+\d+\b"),
    # "the most notable / important / significant …" — editorial-adjective
    # curation. Narrow adjective list so "most often" (analytics) doesn't
    # accidentally route survey.
    re.compile(
        r"\bmost\s+("
        r"notable|important|significant|substantive|prominent|contentious|"
        r"debated|significant|material|consequential|pressing|controversial|"
        r"relevant|influential|cited|discussed|detailed"
        r")\b"
    ),
    # "any fines imposed", "any enforcement actions taken" — open-ended
    # inventory requests across the corpus. Allow 1-2 words between "any"
    # and the verb so "any enforcement actions taken" matches.
    re.compile(r"\bany\s+(?:\w+\s+){1,2}(reported|mentioned|covered|imposed|taken|brought|raised|discussed)\b"),
)

QueryKind = Literal["survey", "factual"]


@dataclass(frozen=True)
class QueryKindResult:
    kind: QueryKind
    signals: List[str]


def _load_cues() -> tuple[str, ...]:
    """Load cue phrases, honouring SURVEY_QUERY_CUES override.

    Env format: comma-separated phrases, lowercased at match time.
    An empty env value falls back to defaults (explicit opt-in to
    override only when the env var is set).
    """
    raw = os.getenv("SURVEY_QUERY_CUES")
    if not raw:
        return _DEFAULT_SURVEY_CUES
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else _DEFAULT_SURVEY_CUES


def classify_query_kind(question: str) -> QueryKindResult:
    """Classify a question as survey (recall-oriented) or factual (precision).

    Returns the kind plus the cues/patterns that fired, for logging and
    for the retrieval_coverage metadata surfaced downstream.
    """
    if not question or not question.strip():
        return QueryKindResult(kind="factual", signals=[])

    lowered = question.lower()
    signals: List[str] = []

    for cue in _load_cues():
        if cue in lowered:
            signals.append(f"cue:{cue}")

    for pattern in _SURVEY_PATTERNS:
        if pattern.search(lowered):
            signals.append(f"pattern:{pattern.pattern}")

    if signals:
        return QueryKindResult(kind="survey", signals=signals)
    return QueryKindResult(kind="factual", signals=[])
