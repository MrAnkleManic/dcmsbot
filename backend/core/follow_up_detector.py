"""Detect follow-up questions that depend on prior conversation context.

The retrieval layer is otherwise topic-less between turns: when a user
asks "is that all?" after a Section-64 question, BM25 + embeddings score
the three-word query against the whole corpus and surface token matches
for "all" / "that" — not the Section 64 chunks the user expects.

This module closes that gap without an LLM call. It classifies a turn as
"follow_up" (depends on prior context) or "new_topic" (stands alone) via
cheap string/length heuristics. When "follow_up" fires, app.py prepends
the last user question to the retrieval input — minimum viable
conversation-aware retrieval per Brief 9 sub-job B.

Design: conservative — default is new_topic unless strong signals fire.
Over-promoting follow-up silently attaches irrelevant prior context to
genuinely new queries; under-promoting at worst leaves the current
behaviour. The LLM rewriter (core/query_rewriter.py) remains a
strictly-better path — it runs after this heuristic when enabled.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Literal, Optional

TurnKind = Literal["follow_up", "new_topic"]


@dataclass(frozen=True)
class TurnKindResult:
    kind: TurnKind
    signals: List[str]


# Explicit follow-up phrases — substring match on the lowercased question.
# These are strong signals on their own: a question containing any of
# these clearly references the previous turn.
_DEFAULT_FOLLOW_UP_PHRASES: tuple[str, ...] = (
    "is that all",
    "is that everything",
    "is that it",
    "anything else",
    "what else",
    "tell me more",
    "more detail",
    "more details",
    "expand on that",
    "expand on this",
    "elaborate",
    "continue",
    "go on",
    "and then",
    "what about",
    "how about",
    "same for",
    "the same",
)

# Pronouns whose referent is expected to come from the previous turn.
# We only treat these as follow-up signals in a short question — a long
# question containing "they" can still be standalone.
_FOLLOW_UP_PRONOUNS: tuple[str, ...] = (
    "it",
    "its",
    "they",
    "them",
    "their",
    "this",
    "that",
    "these",
    "those",
    "he",
    "she",
    "his",
    "her",
)

# A short question with a pronoun strongly implies dependence on context.
# Tune: 6 words is aggressive enough to catch "is that all?" / "tell me
# more about it?" without sweeping genuinely standalone 7-word questions.
_SHORT_QUESTION_WORD_THRESHOLD = 6

_WORD_PATTERN = re.compile(r"\b[a-z']+\b")


def _load_phrases() -> tuple[str, ...]:
    """Load follow-up phrases, honouring FOLLOW_UP_PHRASES override.

    Env format: comma-separated phrases, lowercased at match time.
    An empty env value falls back to defaults.
    """
    raw = os.getenv("FOLLOW_UP_PHRASES")
    if not raw:
        return _DEFAULT_FOLLOW_UP_PHRASES
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    return tuple(parts) if parts else _DEFAULT_FOLLOW_UP_PHRASES


def _tokens(text: str) -> list[str]:
    return _WORD_PATTERN.findall(text.lower())


def _last_user_content(history: List[dict]) -> Optional[str]:
    """Return the most recent user-turn content, or None."""
    for turn in reversed(history):
        if turn.get("role") == "user":
            content = turn.get("content")
            if content:
                return content
    return None


def classify_turn(
    current_question: str,
    history: Optional[List[dict]] = None,
) -> TurnKindResult:
    """Classify whether the current question is a follow-up.

    Args:
        current_question: the user's current question.
        history: [{"role": "user"|"assistant", "content": "..."}, ...]
            in chronological order. Empty or None → new_topic.

    Returns TurnKindResult with kind and the signals that fired.
    """
    if not history or not current_question or not current_question.strip():
        return TurnKindResult(kind="new_topic", signals=[])

    lowered = current_question.lower()
    tokens = _tokens(lowered)
    signals: List[str] = []

    # Signal 1: explicit follow-up phrase.
    for phrase in _load_phrases():
        if phrase in lowered:
            signals.append(f"phrase:{phrase}")

    # Signal 2: short question containing a pronoun. A single-word query
    # ("it?") or a 3–5-word query with a pronoun is almost always a
    # follow-up; longer questions with pronouns may still be standalone.
    if len(tokens) <= _SHORT_QUESTION_WORD_THRESHOLD:
        pronouns_present = [p for p in _FOLLOW_UP_PRONOUNS if p in tokens]
        if pronouns_present:
            signals.append(
                f"short+pronoun:{','.join(pronouns_present)}"
            )
        elif len(tokens) <= 3:
            # A very short question with no pronoun and no phrase hit is
            # still likely a follow-up ("more?" / "others?" / "why?").
            signals.append(f"very_short:{len(tokens)}w")

    # Signal 3: current question starts with a conjunction referring
    # back ("and …", "but …", "so …") — typical continuation markers.
    first_token = tokens[0] if tokens else ""
    if first_token in {"and", "but", "so"}:
        signals.append(f"leading_conjunction:{first_token}")

    if signals:
        return TurnKindResult(kind="follow_up", signals=signals)
    return TurnKindResult(kind="new_topic", signals=[])


def concat_for_retrieval(
    current_question: str,
    history: List[dict],
) -> str:
    """Prepend the last user question to the current one for retrieval.

    Caller is expected to have already classified the turn as follow-up.
    Synthesis layer still receives the original question + full history,
    so the evidence pack is picked from the combined topic but the LLM
    answers the actual follow-up, not the Frankenquestion.
    """
    prior = _last_user_content(history)
    if not prior:
        return current_question
    return f"{prior} {current_question}".strip()
