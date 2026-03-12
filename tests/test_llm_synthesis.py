"""Tests for the multi-turn message building in llm_synthesis.

Verifies that:
- Single-turn behaviour (no history) produces a single user message
- Multi-turn history is correctly prepended as user/assistant pairs
- The character budget is respected (old turns are dropped)
- Edge cases: empty history, malformed entries
"""

from __future__ import annotations

import pytest

from backend.core.llm_synthesis import _build_messages


# ── _build_messages ─────────────────────────────────────────────────────

class TestBuildMessages:
    def test_without_history_returns_single_user_message(self):
        """Existing single-turn behaviour: one user message with evidence + question."""
        messages = _build_messages("What does section 64 say?", "evidence context here")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "What does section 64 say?" in messages[0]["content"]
        assert "evidence context here" in messages[0]["content"]

    def test_with_none_history_returns_single_user_message(self):
        messages = _build_messages("Test question", "evidence", conversation_history=None)
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_with_empty_history_returns_single_user_message(self):
        messages = _build_messages("Test question", "evidence", conversation_history=[])
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_with_history_prepends_turns(self):
        """History turns appear before the current evidence+question message."""
        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers identity verification."},
        ]
        messages = _build_messages("What about section 65?", "evidence", conversation_history=history)
        assert len(messages) == 3  # 2 history + 1 current
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What does section 64 say?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Section 64 covers identity verification."
        assert messages[2]["role"] == "user"
        assert "What about section 65?" in messages[2]["content"]

    def test_respects_char_budget(self):
        """Old turns are dropped when history exceeds the character budget."""
        # Create history that exceeds the default budget (10000 chars)
        long_answer = "A" * 6000
        history = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": long_answer},
            {"role": "user", "content": "Second question"},
            {"role": "assistant", "content": long_answer},
        ]
        messages = _build_messages("Current question", "evidence", conversation_history=history)
        # The second pair (6000+15 chars) fits within 10000.
        # The first pair would push us over. So only the second pair is included.
        # Plus the current user message = 3 messages total.
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Second question"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert "Current question" in messages[2]["content"]

    def test_ensures_first_turn_is_user(self):
        """If the first included turn is assistant, it's skipped to maintain alternation."""
        history = [
            {"role": "assistant", "content": "Orphaned assistant message"},
            {"role": "user", "content": "Follow-up question"},
            {"role": "assistant", "content": "Follow-up answer"},
        ]
        messages = _build_messages("Current question", "evidence", conversation_history=history)
        # The orphaned assistant should be dropped; user + assistant + current = 3
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Follow-up question"

    def test_current_message_always_last(self):
        """The current evidence+question is always the final message."""
        history = [
            {"role": "user", "content": "Previous question"},
            {"role": "assistant", "content": "Previous answer"},
        ]
        messages = _build_messages("Current question", "some evidence", conversation_history=history)
        last = messages[-1]
        assert last["role"] == "user"
        assert "Current question" in last["content"]
        assert "EVIDENCE CHUNKS" in last["content"]

    def test_history_content_preserved(self):
        """History messages are passed through exactly as provided."""
        history = [
            {"role": "user", "content": "What is Ofcom's role?"},
            {"role": "assistant", "content": "Ofcom is the regulatory body..."},
        ]
        messages = _build_messages("Tell me more", "evidence", conversation_history=history)
        assert messages[0]["content"] == "What is Ofcom's role?"
        assert messages[1]["content"] == "Ofcom is the regulatory body..."
