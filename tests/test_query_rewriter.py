"""Tests for the query rewriter module (multi-turn follow-up resolution).

Verifies that:
- The heuristic correctly identifies follow-up vs standalone questions
- The rewrite function calls the LLM when appropriate
- Graceful fallback on errors or suspect output
- History formatting truncates long assistant messages
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.core.query_rewriter import (
    _format_history_for_rewrite,
    _needs_rewriting,
    rewrite_follow_up,
)


# ── _needs_rewriting heuristic ──────────────────────────────────────────

class TestNeedsRewriting:
    def test_returns_false_for_empty_history(self):
        assert _needs_rewriting("What does section 64 say?", []) is False

    def test_returns_false_for_no_history(self):
        assert _needs_rewriting("What does section 64 say?", []) is False

    def test_detects_what_about_follow_up(self):
        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers..."},
        ]
        assert _needs_rewriting("What about section 65?", history) is True

    def test_detects_pronoun_them(self):
        history = [
            {"role": "user", "content": "What is a Category 1 service?"},
            {"role": "assistant", "content": "A Category 1 service is..."},
        ]
        assert _needs_rewriting("What duties apply to them?", history) is True

    def test_detects_tell_me_more(self):
        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers..."},
        ]
        assert _needs_rewriting("Tell me more about that", history) is True

    def test_detects_expand_on(self):
        history = [
            {"role": "user", "content": "What is a regulated service?"},
            {"role": "assistant", "content": "A regulated service is..."},
        ]
        assert _needs_rewriting("Expand on the enforcement part", history) is True

    def test_triggers_for_short_question_with_history(self):
        """Questions with ≤4 words + history always trigger."""
        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers identity verification."},
        ]
        assert _needs_rewriting("And section 65?", history) is True

    def test_returns_false_for_standalone_question(self):
        """A standalone question with no follow-up signals should not trigger."""
        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers..."},
        ]
        assert _needs_rewriting("What are the duties of Category 1 service providers under the Online Safety Act?", history) is False


# ── _format_history_for_rewrite ─────────────────────────────────────────

class TestFormatHistory:
    def test_truncates_long_assistant_messages(self):
        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "A" * 500},
        ]
        formatted = _format_history_for_rewrite(history, max_turns=3)
        assert "..." in formatted
        # The assistant content should be ~300 chars + "..."
        lines = formatted.split("\n")
        assistant_line = [l for l in lines if l.startswith("Assistant:")][0]
        # Remove "Assistant: " prefix, check length
        content_part = assistant_line[len("Assistant: "):]
        assert len(content_part) < 350  # 300 + "..."

    def test_keeps_short_messages_intact(self):
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        formatted = _format_history_for_rewrite(history, max_turns=3)
        assert "Hello" in formatted
        assert "Hi there" in formatted
        assert "..." not in formatted

    def test_respects_max_turns(self):
        history = [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "A1"},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "A2"},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "content": "A3"},
        ]
        formatted = _format_history_for_rewrite(history, max_turns=1)
        # max_turns=1 → last 2 entries (1 pair)
        assert "Q3" in formatted
        assert "A3" in formatted
        assert "Q1" not in formatted


# ── rewrite_follow_up ───────────────────────────────────────────────────

class TestRewriteFollowUp:
    def test_returns_original_when_no_history(self):
        question = "What does section 64 say?"
        result, was_rewritten = rewrite_follow_up(question, None)
        assert result == question
        assert was_rewritten is False

    def test_returns_original_when_empty_history(self):
        question = "What does section 64 say?"
        result, was_rewritten = rewrite_follow_up(question, [])
        assert result == question
        assert was_rewritten is False

    def test_returns_original_for_standalone_question(self):
        """A standalone question with no follow-up signals should pass through."""
        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers..."},
        ]
        question = "What are the duties of Category 1 service providers under the Online Safety Act?"
        result, was_rewritten = rewrite_follow_up(question, history)
        assert result == question
        assert was_rewritten is False

    @patch("backend.core.query_rewriter.anthropic.Anthropic")
    def test_calls_llm_and_returns_rewritten(self, mock_anthropic_cls):
        """When rewriting is needed, the LLM is called and the result returned."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="What does section 65 of the Online Safety Act say?")]
        mock_client.messages.create.return_value = mock_response

        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers identity verification."},
        ]
        result, was_rewritten = rewrite_follow_up("What about section 65?", history)
        assert result == "What does section 65 of the Online Safety Act say?"
        assert was_rewritten is True
        mock_client.messages.create.assert_called_once()

    @patch("backend.core.query_rewriter.anthropic.Anthropic")
    def test_falls_back_on_api_error(self, mock_anthropic_cls):
        """When the API call fails, the original question is returned."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API error")

        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers identity verification."},
        ]
        result, was_rewritten = rewrite_follow_up("What about section 65?", history)
        assert result == "What about section 65?"
        assert was_rewritten is False

    @patch("backend.core.query_rewriter.anthropic.Anthropic")
    def test_falls_back_on_empty_rewrite(self, mock_anthropic_cls):
        """When the LLM returns empty text, the original is returned."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="")]
        mock_client.messages.create.return_value = mock_response

        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers identity verification."},
        ]
        result, was_rewritten = rewrite_follow_up("What about section 65?", history)
        assert result == "What about section 65?"
        assert was_rewritten is False

    @patch("backend.core.query_rewriter.anthropic.Anthropic")
    def test_falls_back_on_suspiciously_long_output(self, mock_anthropic_cls):
        """When the rewrite is >3x the original length, fall back."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_response = MagicMock()
        # Return something absurdly long
        mock_response.content = [MagicMock(text="A" * 1000)]
        mock_client.messages.create.return_value = mock_response

        history = [
            {"role": "user", "content": "What does section 64 say?"},
            {"role": "assistant", "content": "Section 64 covers identity verification."},
        ]
        result, was_rewritten = rewrite_follow_up("What about section 65?", history)
        assert result == "What about section 65?"
        assert was_rewritten is False
