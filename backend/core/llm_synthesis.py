"""LLM synthesis layer: generates answers from retrieved evidence chunks using Claude."""

from __future__ import annotations

import os
from typing import List, Optional

import anthropic

from backend import config
from backend.core.models import Answer, Citation, Confidence, KBChunk
from backend.logging_config import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = """\
You are the DCMS Online Safety Evidence Bot. You answer questions about the \
Online Safety Act 2023 and related UK legislation, guidance, and parliamentary debates.

RULES — follow these strictly:
1. Use ONLY the evidence chunks provided below. Never use your training knowledge \
for factual claims about the legislation.
2. Every factual claim must cite a specific chunk using its citation ID in square \
brackets, e.g. [C001].
3. When quoting statutory text, reproduce it accurately from the chunk.
4. If the evidence does not contain enough information to fully answer the question, \
provide a HELPFUL refusal that includes:
   a) A brief summary of what partial evidence WAS found (e.g. "I found 5 chunks \
mentioning search service duties under sections 28-30, and 8 chunks about user-to-user \
service duties under sections 11-27, but none that directly compare the two regimes.")
   b) 2-3 specific alternative questions the user could ask instead, formatted as a \
bullet list. Base these on the topics and sections you can see in the evidence chunks.
   c) If the evidence chunks come from only one or two source types, suggest the user \
check whether other document filters (e.g. Select Committee Evidence, Parliamentary \
Debates, Regulator Guidance) might contain relevant material.
   Do NOT guess or speculate about facts not in the evidence. Keep the refusal concise.
5. Structure your answer clearly. For section-specific questions, lead with the \
section content. For thematic questions, organise by topic.
6. Keep answers concise and focused on what was asked.
7. When a chunk includes a location pointer (e.g. "Section 44"), reference it \
naturally in your answer (e.g. "Section 44 of the Online Safety Act 2023 provides...").
"""


def _format_chunk_context(evidence: List[KBChunk], citations: List[Citation]) -> str:
    """Format evidence chunks into a context block for the LLM prompt."""
    parts: list[str] = []
    for chunk, citation in zip(evidence, citations):
        header = f"[{citation.citation_id}] {citation.title}"
        if citation.location_pointer:
            header += f" — {citation.location_pointer}"
        header += f" (source_type: {citation.source_type}, authority_weight: {citation.authority_weight})"
        parts.append(f"{header}\n{chunk.chunk_text}")
    return "\n\n---\n\n".join(parts)


def _build_user_prompt(question: str, context: str) -> str:
    return (
        f"EVIDENCE CHUNKS:\n\n{context}\n\n---\n\n"
        f"QUESTION: {question}\n\n"
        "Answer the question using only the evidence above. "
        "Cite each claim with the relevant [C###] citation ID."
    )


def _build_messages(
    question: str,
    context: str,
    conversation_history: Optional[List[dict]] = None,
) -> list[dict]:
    """Build the messages array for the Claude API call.

    For multi-turn conversations, includes previous turns as user/assistant
    message pairs before the current evidence-laden user message.  A sliding
    window based on ``config.CONVERSATION_MAX_HISTORY_CHARS`` keeps the total
    history within budget.

    The Anthropic Messages API requires strict user/assistant alternation.
    The history from the frontend is already in this format by construction
    (user asks, bot answers, …).  If malformed entries appear they are
    silently skipped.
    """
    messages: list[dict] = []

    if conversation_history:
        max_chars = config.CONVERSATION_MAX_HISTORY_CHARS
        char_count = 0
        turns_to_include: list[dict] = []

        # Walk backwards, accumulating turns until budget is hit
        for turn in reversed(conversation_history):
            turn_chars = len(turn.get("content", ""))
            if char_count + turn_chars > max_chars:
                break
            turns_to_include.insert(0, turn)
            char_count += turn_chars

        # Ensure strict alternation: first included turn must be "user"
        while turns_to_include and turns_to_include[0].get("role") != "user":
            turns_to_include.pop(0)

        # Drop a trailing assistant message (current turn is user)
        # — not needed since we append the current user message below,
        # but guard against a malformed history ending with assistant.
        # Actually, having the last history entry be "assistant" is fine
        # because the next message we append is "user".

        for turn in turns_to_include:
            messages.append({
                "role": turn["role"],
                "content": turn["content"],
            })

    # Current turn: evidence chunks + question
    user_prompt = _build_user_prompt(question, context)
    messages.append({"role": "user", "content": user_prompt})

    return messages


def _extract_confidence(
    answer_text: str,
    evidence: List[KBChunk],
    confidence_label: str,
) -> str:
    """Map evidence signals confidence into a human-readable indicator."""
    if confidence_label == "high":
        return "strong"
    if confidence_label == "medium":
        return "partial"
    return "insufficient"


def synthesise_answer(
    question: str,
    evidence: List[KBChunk],
    citations: List[Citation],
    section_lock: str | None = None,
    target_section: int | None = None,
    confidence_label: str = "medium",
    conversation_history: Optional[List[dict]] = None,
) -> Answer:
    """Call Claude to synthesise an answer from retrieved evidence chunks.

    Returns an Answer with the LLM-generated text and inline citations.
    Falls back to a refusal if the API call fails.
    """
    if not evidence or not citations:
        return Answer(
            text="No evidence available to generate an answer.",
            confidence=Confidence(level="low", reason="No evidence chunks provided."),
            refused=True,
            refusal_reason="No evidence chunks provided.",
            section_lock=section_lock,
        )

    context = _format_chunk_context(evidence, citations)
    messages = _build_messages(question, context, conversation_history)

    try:
        client = anthropic.Anthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            timeout=config.LLM_TIMEOUT_SECONDS,
        )
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.LLM_MAX_TOKENS,
            temperature=config.LLM_TEMPERATURE,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )
        answer_text = response.content[0].text
    except Exception:
        logger.exception("LLM synthesis failed")
        return Answer(
            text="LLM synthesis encountered an error. Falling back to evidence excerpts.",
            confidence=Confidence(level="low", reason="LLM call failed."),
            refused=True,
            refusal_reason="LLM synthesis error.",
            section_lock=section_lock,
        )

    # Check if the LLM itself said it couldn't answer
    refusal_phrases = [
        "does not contain enough information",
        "cannot answer",
        "no relevant information",
        "not enough evidence",
        "couldn't find sufficient evidence",
        "could not find sufficient evidence",
        "i found",  # our new helpful refusal format starts with partial evidence summary
    ]
    lower_text = answer_text.lower()
    # Only treat "i found" as a refusal if it also contains refusal-like language
    llm_refused = any(
        phrase in lower_text
        for phrase in refusal_phrases
        if phrase != "i found"
    ) or (
        "i found" in lower_text
        and any(kw in lower_text for kw in ["but none", "however", "insufficient", "not enough", "couldn't find", "could not find"])
    )

    strength = _extract_confidence(answer_text, evidence, confidence_label)

    return Answer(
        text=answer_text,
        confidence=Confidence(
            level=confidence_label if not llm_refused else "low",
            reason=f"Evidence strength: {strength}.",
        ),
        refused=llm_refused,
        refusal_reason=answer_text if llm_refused else None,
        section_lock=section_lock,
        allow_citations_on_refusal=llm_refused,
    )
