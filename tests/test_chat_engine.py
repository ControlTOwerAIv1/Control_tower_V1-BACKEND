"""
tests/test_chat_engine.py
==========================
Unit tests for ai/chat_engine.py -- Claude API wrapper.

All tests mock the Anthropic SDK; no real API calls are made.
"""

import os
from unittest.mock import patch, MagicMock

import pytest

from ai.chat_engine import call_claude, parse_claude_response


class TestCallClaude:
    """Tests for the call_claude function."""

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
    def test_raises_runtime_error_when_api_key_missing(self):
        """call_claude should raise RuntimeError when ANTHROPIC_API_KEY is unset."""
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            call_claude("some context", "some question")

    def test_raises_value_error_when_context_empty(self):
        """call_claude should raise ValueError when context is empty."""
        with pytest.raises(ValueError, match="context"):
            call_claude("", "some question")

    def test_raises_value_error_when_question_empty(self):
        """call_claude should raise ValueError when question is empty."""
        with pytest.raises(ValueError, match="question"):
            call_claude("some context", "")


class TestParseClaudeResponse:
    """Tests for the parse_claude_response function."""

    def test_raises_runtime_error_on_no_content(self):
        """Response with no content blocks should raise RuntimeError."""
        mock_response = MagicMock()
        mock_response.content = []
        with pytest.raises(RuntimeError, match="empty"):
            parse_claude_response(mock_response)

    def test_extracts_text_from_single_block(self):
        """Should correctly extract text from a response with one text block."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Hello, this is the answer."

        mock_response = MagicMock()
        mock_response.content = [text_block]

        result = parse_claude_response(mock_response)
        assert result == "Hello, this is the answer."

    def test_skips_non_text_blocks_returns_text(self):
        """Non-text blocks should be skipped; text from text blocks returned."""
        image_block = MagicMock()
        image_block.type = "image"
        image_block.text = ""

        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Actual answer here."

        mock_response = MagicMock()
        mock_response.content = [image_block, text_block]

        result = parse_claude_response(mock_response)
        assert result == "Actual answer here."

    def test_raises_on_none_response(self):
        """None response should raise RuntimeError."""
        with pytest.raises(RuntimeError, match="None"):
            parse_claude_response(None)

    def test_raises_when_all_blocks_non_text(self):
        """Response with only non-text blocks should raise RuntimeError."""
        image_block = MagicMock()
        image_block.type = "image"
        image_block.text = ""

        mock_response = MagicMock()
        mock_response.content = [image_block]

        with pytest.raises(RuntimeError, match="none of type"):
            parse_claude_response(mock_response)
