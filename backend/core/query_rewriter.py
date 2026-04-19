"""Rewrite follow-up questions into standalone queries using conversation context.

When a user asks a follow-up like "And what about section 65?" after asking
about section 64, this module rewrites it into a standalone question that the
retrieval pipeline can handle directly — e.g. "What does section 65 of the
Online Safety Act say?"

Design:
- A fast heuristic (_needs_rewriting) gates the LLM call to avoid latency on
  standalone questions.
- The LLM rewrite uses temperature=0 for deterministic output.
- Graceful fallback: any error returns the original question unchanged.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import anthropic

from backend import config
from backend.core.usage import UsageAggregator
from backend.logging_config import get_logger

logger = get_logger(__name__)

_REWRITE_SYSTEM_PROMPT = """\
You are a query rewriter for a UK legislation knowledge base about the Online Safety Act 2023.

Given a conversation history and a follow-up question, rewrite the follow-up into a \
standalone question that can be understood without the conversation history.

Rules:
1. Resolve all pronouns (it, they, them, this, that, these, those) to their referents \
from the conversation.
2. Resolve references like "and what about...", "the same for...", "that section" to \
explicit entities mentioned in the conversation.
3. Preserve the user's intent exactly — do not add or remove meaning.
4. If the question is already standalone, return it unchanged.
5. Return ONLY the rewritten question, nothing else. No explanation, no preamble."""

# Phrases that signal a follow-up dependency on prior context.
_FOLLOW_UP_SIGNALS = [
    "what about", "and what", "how about",
    "what are they", "what does it", "what do they", "what are those",
    "the same", "that section", "this section", "those duties",
    "them?", "it?", "this?", "that?", "these?", "those?",
    "tell me more", "expand on", "elaborate",
    "also,", "additionally", "furthermore",
    "can you clarify", "more detail",
]

# Short-question word threshold: questions this short with history present
# are likely follow-ups even without explicit signal phrases.
_SHORT_QUESTION_WORDS = 4


def _needs_rewriting(question: str, history: List[dict]) -> bool:
    """Quick heuristic: does this question likely need rewriting?

    Returns True if the question contains follow-up signals or is very short
    (suggesting it depends on prior context). Returns False for standalone
    questions or when there is no conversation history.
    """
    if not history:
        return False
    lowered = question.lower().strip()
    # Very short questions with history are likely follow-ups
    if len(lowered.split()) <= _SHORT_QUESTION_WORDS:
        return True
    return any(signal in lowered for signal in _FOLLOW_UP_SIGNALS)


def _format_history_for_rewrite(history: List[dict], max_turns: int) -> str:
    """Format recent conversation turns for the rewrite prompt.

    Assistant responses are truncated to ~300 chars since the rewriter only
    needs enough context to resolve references, not the full answer text.
    """
    recent = history[-(max_turns * 2):]  # max_turns pairs = max_turns * 2 entries
    lines = []
    for turn in recent:
        role_label = "User" if turn["role"] == "user" else "Assistant"
        content = turn["content"]
        if role_label == "Assistant" and len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"{role_label}: {content}")
    return "\n".join(lines)


def rewrite_follow_up(
    question: str,
    conversation_history: Optional[List[dict]] = None,
    usage_sink: Optional[UsageAggregator] = None,
) -> Tuple[str, bool]:
    """Rewrite a follow-up question into a standalone question.

    Args:
        question: The current user question.
        conversation_history: List of {"role": "user"|"assistant", "content": "..."} dicts.

    Returns:
        Tuple of (rewritten_question, was_rewritten).
        If no rewriting was needed or possible, returns (original_question, False).
    """
    if not conversation_history or not _needs_rewriting(question, conversation_history):
        return question, False

    history_text = _format_history_for_rewrite(
        conversation_history,
        max_turns=config.CONVERSATION_MAX_HISTORY_TURNS,
    )

    user_prompt = (
        f"Conversation so far:\n{history_text}\n\n"
        f"Follow-up question: {question}\n\n"
        "Rewritten standalone question:"
    )

    try:
        client = anthropic.Anthropic(
            api_key=config.anthropic_api_key(),
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=256,
            temperature=0.0,
            system=_REWRITE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        if usage_sink is not None:
            usage_sink.record_anthropic(
                "rewriter", config.ANTHROPIC_MODEL, response.usage
            )
        rewritten = response.content[0].text.strip()

        # Sanity checks: empty or suspiciously long output → fall back
        if not rewritten:
            logger.warning(
                "Query rewrite returned empty output, using original",
                extra={"original": question},
            )
            return question, False

        if len(rewritten) > len(question) * 3:
            logger.warning(
                "Query rewrite produced suspiciously long output, using original",
                extra={"original": question, "rewritten_len": len(rewritten)},
            )
            return question, False

        logger.info(
            "Query rewritten for multi-turn context",
            extra={"original": question, "rewritten": rewritten},
        )
        return rewritten, True

    except Exception:
        logger.exception("Query rewrite failed, using original question")
        return question, False
