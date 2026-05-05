"""
rag/response_cache.py
==============================
In-memory response cache for normalized user questions.
"""

import logging
import re
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def normalize_question(question: str) -> str:
    if not isinstance(question, str):
        raise TypeError(f"question must be a string, got {type(question).__name__}")

    normalised = question.strip().lower()
    normalised = re.sub(r"[^\w\s]", "", normalised)
    normalised = re.sub(r"\s+", " ", normalised).strip()

    return normalised


def get_cached_response(question: str) -> Optional[Dict[str, Any]]:
    key = normalize_question(question)

    if not key:
        logger.debug("Normalised question is empty; treating as cache miss.")
        return None

    with _cache_lock:
        entry = _cache.get(key)

    if entry is not None:
        logger.info("Cache HIT for question key: '%s'", key[:80])
    else:
        logger.debug("Cache MISS for question key: '%s'", key[:80])

    return entry


def store_response(question: str, answer: str, snapshot_time: str) -> None:
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
        logger.warning("Normalised question is empty; skipping cache storage.")
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
    with _cache_lock:
        count = len(_cache)
        _cache.clear()

    if count > 0:
        logger.info("Response cache invalidated; %d entries cleared.", count)
    else:
        logger.debug("Response cache invalidated; cache was already empty.")


def get_cache_stats() -> Dict[str, Any]:
    with _cache_lock:
        total = len(_cache)

        if total == 0:
            return {
                "total_entries": 0,
                "oldest_entry": None,
                "newest_entry": None,
            }

        timestamps = [entry["cached_at"] for entry in _cache.values()]

    timestamps.sort()

    return {
        "total_entries": total,
        "oldest_entry": timestamps[0],
        "newest_entry": timestamps[-1],
    }
