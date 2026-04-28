"""
ai/memory.py
=============
In-memory conversation history store for the chatbot.

Stores message history per session_id in a plain Python dict.
Thread-safe via a threading lock. No external dependencies.

Usage:
    from ai.memory import add_message, get_history, clear_session

    add_message("session-1", "user", "What is the stock level?")
    add_message("session-1", "assistant", "Product X has 50 units.")
    history = get_history("session-1")
    formatted = format_history_for_prompt("session-1")
    clear_session("session-1")
"""

import threading
from typing import Dict, List

# Module-level store: session_id -> list of message dicts
_store: Dict[str, List[Dict[str, str]]] = {}
_lock = threading.Lock()

# Maximum messages kept per session to prevent unbounded growth
_MAX_MESSAGES: int = 20

# Allowed roles
_VALID_ROLES = {"user", "assistant"}


def add_message(session_id: str, role: str, content: str) -> None:
    """
    Append a message to the session's conversation history.

    Args:
        session_id: Unique identifier for the conversation session.
        role: Must be 'user' or 'assistant'.
        content: The message text.

    Raises:
        ValueError: If role is not 'user' or 'assistant'.
    """
    if role not in _VALID_ROLES:
        raise ValueError(
            f"Invalid role '{role}'. Allowed roles: {', '.join(sorted(_VALID_ROLES))}"
        )

    with _lock:
        if session_id not in _store:
            _store[session_id] = []

        _store[session_id].append({"role": role, "content": content})

        # Trim to last N messages
        if len(_store[session_id]) > _MAX_MESSAGES:
            _store[session_id] = _store[session_id][-_MAX_MESSAGES:]


def get_history(session_id: str) -> List[Dict[str, str]]:
    """
    Return the full message history for a session.

    Args:
        session_id: Unique identifier for the conversation session.

    Returns:
        List of message dicts. Empty list if session does not exist.
    """
    with _lock:
        return list(_store.get(session_id, []))


def clear_session(session_id: str) -> None:
    """
    Delete all history for a session.

    Does nothing if the session does not exist.

    Args:
        session_id: Unique identifier for the conversation session.
    """
    with _lock:
        _store.pop(session_id, None)


def format_history_for_prompt(session_id: str) -> str:
    """
    Format conversation history as a string for inclusion in the Claude
    system prompt.

    Each message is formatted as 'User: <content>' or 'Assistant: <content>'
    on its own line.

    Args:
        session_id: Unique identifier for the conversation session.

    Returns:
        Formatted history string. Empty string if history is empty.
    """
    history = get_history(session_id)
    if not history:
        return ""

    lines = []
    for msg in history:
        prefix = "User" if msg["role"] == "user" else "Assistant"
        lines.append(f"{prefix}: {msg['content']}")

    return "\n".join(lines)
