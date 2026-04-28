"""
tests/test_memory.py
=====================
Unit tests for ai/memory.py -- conversation memory system.
"""

import pytest

from ai.memory import (
    add_message,
    get_history,
    clear_session,
    format_history_for_prompt,
    _store,
    _lock,
)


@pytest.fixture(autouse=True)
def _clean_store():
    """Clear the memory store before and after each test."""
    with _lock:
        _store.clear()
    yield
    with _lock:
        _store.clear()


class TestAddMessage:
    """Tests for add_message."""

    def test_appends_to_history(self):
        """add_message should append a message dict to the session."""
        add_message("s1", "user", "hello")
        history = get_history("s1")
        assert len(history) == 1
        assert history[0] == {"role": "user", "content": "hello"}

    def test_multiple_messages(self):
        """Multiple messages should be appended in order."""
        add_message("s1", "user", "q1")
        add_message("s1", "assistant", "a1")
        add_message("s1", "user", "q2")
        history = get_history("s1")
        assert len(history) == 3
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "user"

    def test_invalid_role_raises_value_error(self):
        """An invalid role should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid role"):
            add_message("s1", "system", "not allowed")

    def test_history_truncated_to_20(self):
        """History should be truncated to the last 20 messages."""
        for i in range(25):
            add_message("s1", "user", f"message {i}")

        history = get_history("s1")
        assert len(history) == 20
        # First message should be message 5 (oldest 5 were trimmed)
        assert history[0]["content"] == "message 5"
        assert history[-1]["content"] == "message 24"


class TestGetHistory:
    """Tests for get_history."""

    def test_returns_empty_list_for_unknown_session(self):
        """Unknown session should return an empty list, not raise."""
        result = get_history("nonexistent")
        assert result == []

    def test_returns_copy(self):
        """Returned list should be a copy, not the internal list."""
        add_message("s1", "user", "hello")
        history = get_history("s1")
        history.append({"role": "user", "content": "injected"})
        assert len(get_history("s1")) == 1  # internal store unchanged


class TestClearSession:
    """Tests for clear_session."""

    def test_removes_all_history(self):
        """clear_session should remove all messages for the session."""
        add_message("s1", "user", "hello")
        add_message("s1", "assistant", "hi")
        clear_session("s1")
        assert get_history("s1") == []

    def test_no_error_for_unknown_session(self):
        """clear_session on unknown session should not raise."""
        clear_session("nonexistent")  # Should not raise


class TestFormatHistoryForPrompt:
    """Tests for format_history_for_prompt."""

    def test_returns_empty_string_for_empty_history(self):
        """Empty or unknown session should return empty string."""
        result = format_history_for_prompt("nonexistent")
        assert result == ""

    def test_formats_messages_correctly(self):
        """Messages should be formatted with User: and Assistant: prefixes."""
        add_message("s1", "user", "What is the stock?")
        add_message("s1", "assistant", "Product X has 50 units.")
        add_message("s1", "user", "Should I reorder?")

        result = format_history_for_prompt("s1")
        lines = result.split("\n")

        assert lines[0] == "User: What is the stock?"
        assert lines[1] == "Assistant: Product X has 50 units."
        assert lines[2] == "User: Should I reorder?"
