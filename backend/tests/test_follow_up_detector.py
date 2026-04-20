"""Tests for conversation-aware retrieval (Brief 9 sub-job B).

classify_turn gates when the retrieval layer should inherit topic from
the previous user question. Over-promoting follow-up silently attaches
stale context to genuinely new questions; under-promoting at worst
preserves current behaviour.
"""

from __future__ import annotations

import pytest

from backend.core.follow_up_detector import (
    classify_turn,
    concat_for_retrieval,
)


def _history(pairs: list[tuple[str, str]]) -> list[dict]:
    """Build [{role: user/assistant, content: …}] from (user, asst) tuples."""
    out: list[dict] = []
    for user_q, asst_a in pairs:
        out.append({"role": "user", "content": user_q})
        out.append({"role": "assistant", "content": asst_a})
    return out


class TestEmptyOrNoHistory:
    def test_no_history_is_new_topic(self):
        result = classify_turn("What does Section 64 say?", history=None)
        assert result.kind == "new_topic"
        assert result.signals == []

    def test_empty_history_is_new_topic(self):
        result = classify_turn("What does Section 64 say?", history=[])
        assert result.kind == "new_topic"

    def test_empty_question_is_new_topic(self):
        history = _history([("q", "a")])
        result = classify_turn("", history=history)
        assert result.kind == "new_topic"


class TestExplicitFollowUpPhrases:
    """The strongest signal — an explicit continuation phrase."""

    @pytest.mark.parametrize(
        "question",
        [
            "Is that all?",
            "Is that everything?",
            "Anything else?",
            "What else?",
            "Tell me more",
            "Can you elaborate?",
            "Expand on that",
            "And what about Ofcom's position?",
            "How about Hansard?",
            "Continue",
            "Go on",
        ],
    )
    def test_phrase_promotes_to_follow_up(self, question):
        history = _history([("What are the duties under Section 11?", "…")])
        result = classify_turn(question, history=history)
        assert result.kind == "follow_up", (
            f"Expected follow_up for {question!r}; signals={result.signals}"
        )


class TestShortPronounQuestions:
    """Short questions whose referent must be the previous turn."""

    def test_short_pronoun_is_follow_up(self):
        history = _history([("Who is the regulator?", "Ofcom")])
        result = classify_turn("When was it established?", history=history)
        assert result.kind == "follow_up"

    def test_single_word_question_is_follow_up(self):
        history = _history([("What does Section 11 say?", "…")])
        result = classify_turn("Why?", history=history)
        assert result.kind == "follow_up"

    def test_longer_pronoun_question_still_standalone(self):
        # Seven words with 'they' — crosses the short-question threshold;
        # stays new_topic since no explicit phrase fires.
        history = _history([("Section 11 q", "…")])
        result = classify_turn(
            "Which enforcement powers were they applied under frequently?",
            history=history,
        )
        assert result.kind == "new_topic"


class TestLeadingConjunction:
    def test_leading_and_promotes(self):
        history = _history([("What are the Section 10 duties?", "…")])
        result = classify_turn(
            "And what about the Section 11 duties?", history=history
        )
        assert result.kind == "follow_up"
        assert any(s.startswith("leading_conjunction:and") for s in result.signals)

    def test_leading_but_promotes(self):
        history = _history([("q", "a")])
        result = classify_turn(
            "But what did the Select Committee conclude on that point?", history=history
        )
        assert result.kind == "follow_up"


class TestNewTopicPreservation:
    """The dual risk — long, topic-rich questions must stay standalone."""

    def test_proper_noun_rich_question_is_new_topic(self):
        history = _history([("Ofcom enforcement question", "…")])
        result = classify_turn(
            "What does Section 64 of the Online Safety Act say about record-keeping?",
            history=history,
        )
        assert result.kind == "new_topic"

    def test_long_question_without_phrase_is_new_topic(self):
        history = _history([("Section 11 q", "…")])
        result = classify_turn(
            "Summarise the parliamentary debates on age verification during 2023",
            history=history,
        )
        assert result.kind == "new_topic"


class TestConcatForRetrieval:
    def test_prepends_last_user_question(self):
        history = _history([
            ("Main debates on online safety duties", "Parliament discussed …"),
        ])
        combined = concat_for_retrieval("is that all?", history=history)
        assert combined == "Main debates on online safety duties is that all?"

    def test_prepends_only_user_not_assistant(self):
        history = [
            {"role": "user", "content": "original user question"},
            {"role": "assistant", "content": "long answer text"},
            {"role": "user", "content": "second user question"},
            {"role": "assistant", "content": "second answer"},
        ]
        combined = concat_for_retrieval("tell me more", history=history)
        # Picks the *most recent* user question.
        assert combined.startswith("second user question")
        assert "long answer text" not in combined

    def test_empty_history_returns_current_only(self):
        assert concat_for_retrieval("q?", history=[]) == "q?"

    def test_history_without_user_turns_returns_current_only(self):
        history = [{"role": "assistant", "content": "hi"}]
        assert concat_for_retrieval("q?", history=history) == "q?"


class TestAcceptanceCriterionBriefB:
    """Named criterion: 'is that all?' after a topical question preserves
    the topic through concat_for_retrieval."""

    def test_is_that_all_after_section_question_preserves_topic(self):
        topical_q = "What duties does Section 11 impose on user-to-user services?"
        history = _history([(topical_q, "Section 11 establishes …")])
        result = classify_turn("is that all?", history=history)
        assert result.kind == "follow_up"
        combined = concat_for_retrieval("is that all?", history=history)
        assert "Section 11" in combined
        assert "user-to-user" in combined
