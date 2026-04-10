"""
cache/response_cache.py
========================
Store and retrieve answers to previously asked questions.  If a user asks
the same question again (or a normalised version of it), return the cached
answer instantly — no Claude API call, no DB call.

Edge cases handled:
    - Question with only punctuation/whitespace → normalises to empty → cache miss
    - Cache is empty → get_cache_stats returns zero entries
    - invalidate_cache on empty cache → no-op (no error)
    - Concurrent reads/writes → protected by a threading lock
    - Very long questions → cached by their normalised form

Input validations:
    - question must be a non-empty string (after normalisation)
    - answer must be a non-empty string
    - snapshot_time must be a non-empty string

Assumptions NOT made:
    - Not assuming questions are always well-formed
    - Not assuming cache is bounded (no eviction policy — cleared on refresh)
    - Not assuming single-threaded access
"""

import logging
import re
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def normalize_question(question: str) -> str:
    """
    Normalise a question string to produce a stable cache key.

    Transformations applied:
        1. Strip leading/trailing whitespace
        2. Convert to lowercase
        3. Remove all punctuation characters
        4. Collapse multiple spaces into a single space

    Args:
        question: The raw user question.

    Returns:
        A normalised version of the question suitable as a cache key.

    Raises:
        TypeError: If question is not a string.
    """
    if not isinstance(question, str):
        raise TypeError(f"question must be a string, got {type(question).__name__}")

    # Strip and lowercase
    normalised = question.strip().lower()

    # Remove punctuation (keep alphanumeric and spaces)
    normalised = re.sub(r"[^\w\s]", "", normalised)

    # Collapse multiple whitespace into single space
    normalised = re.sub(r"\s+", " ", normalised).strip()

    return normalised


def get_cached_response(question: str) -> Optional[Dict[str, Any]]:
    """
    Look up a cached response for the given question.

    Args:
        question: The raw user question (will be normalised internally).

    Returns:
        A dict with keys 'answer', 'cached_at', 'snapshot_time' if found,
        or None if no cached response exists.

    Raises:
        TypeError: If question is not a string.
    """
    key = normalize_question(question)

    if not key:
        logger.debug("Normalised question is empty — treating as cache miss.")
        return None

    with _cache_lock:
        entry = _cache.get(key)

    if entry is not None:
        logger.info("Cache HIT for question key: '%s'", key[:80])
    else:
        logger.debug("Cache MISS for question key: '%s'", key[:80])

    return entry


def store_response(question: str, answer: str, snapshot_time: str) -> None:
    """
    Store a Claude response in the cache, keyed by the normalised question.

    Args:
        question: The raw user question.
        answer: The Claude-generated response text.
        snapshot_time: The snapshot timestamp the answer was based on.

    Raises:
        TypeError: If any argument is not a string.
        ValueError: If answer or snapshot_time is empty.
    """
    if not isinstance(question, str):
        raise TypeError(f"question must be a string, got {type(question).__name__}")
    if not isinstance(answer, str):
        raise TypeError(f"answer must be a string, got {type(answer).__name__}")
    if not isinstance(snapshot_time, str):
        raise TypeError(
            f"snapshot_time must be a string, got {type(snapshot_time).__name__}"
        )

    if not answer.strip():
        raise ValueError("answer must not be empty")
    if not snapshot_time.strip():
        raise ValueError("snapshot_time must not be empty")

    key = normalize_question(question)

    if not key:
        logger.warning(
            "Normalised question is empty — skipping cache storage."
        )
        return

    entry = {
        "answer": answer,
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot_time": snapshot_time,
    }

    with _cache_lock:
        _cache[key] = entry

    logger.info("Cached response for question key: '%s'", key[:80])


def invalidate_cache() -> None:
    """
    Clear all cached responses.

    Must be called every time the snapshot is refreshed so that stale
    answers based on old data are not returned.
    """
    with _cache_lock:
        count = len(_cache)
        _cache.clear()

    if count > 0:
        logger.info("Response cache invalidated — %d entries cleared.", count)
    else:
        logger.debug("Response cache invalidated — cache was already empty.")


def get_cache_stats() -> Dict[str, Any]:
    """
    Return statistics about the current response cache.

    Returns:
        Dict containing:
            total_entries: Number of cached responses.
            oldest_entry: Timestamp of the oldest cached response (or None).
            newest_entry: Timestamp of the newest cached response (or None).
    """
    with _cache_lock:
        total = len(_cache)

        if total == 0:
            return {
                "total_entries": 0,
                "oldest_entry": None,
                "newest_entry": None,
            }

        timestamps = [entry["cached_at"] for entry in _cache.values()]

    # Timestamps are ISO-formatted strings — lexicographic sort works
    timestamps.sort()

    return {
        "total_entries": total,
        "oldest_entry": timestamps[0],
        "newest_entry": timestamps[-1],
    }
