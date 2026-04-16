"""
rag/cache_backend.py
=============================
Versioned response cache with Redis-first and in-memory fallback.
"""

import hashlib
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VersionedResponseCache:
    def __init__(self) -> None:
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._redis = self._init_redis_client()

    @staticmethod
    def _normalize_question(question: str) -> str:
        return " ".join(question.strip().lower().split())

    def _build_key(self, question: str, data_version: str) -> str:
        normalized = self._normalize_question(question)
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"rag:answer:{data_version}:{digest}"

    def _init_redis_client(self):
        url = os.getenv("REDIS_URL", "").strip()
        if not url:
            logger.info("REDIS_URL not set. Using in-memory response cache.")
            return None

        try:
            import redis

            client = redis.Redis.from_url(url, decode_responses=True)
            client.ping()
            logger.info("Redis cache connected.")
            return client
        except Exception as exc:
            logger.warning("Redis unavailable (%s). Falling back to in-memory cache.", exc)
            return None

    def get(self, question: str, data_version: str) -> Optional[Dict[str, Any]]:
        key = self._build_key(question, data_version)

        if self._redis is not None:
            try:
                raw = self._redis.get(key)
                if raw:
                    import json

                    return json.loads(raw)
                return None
            except Exception as exc:
                logger.warning("Redis get failed, falling back to memory: %s", exc)

        now = time.time()
        with self._lock:
            entry = self._memory.get(key)
            if not entry:
                return None
            if entry["expires_at"] < now:
                del self._memory[key]
                return None
            return entry["payload"]

    def set(self, question: str, data_version: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
        key = self._build_key(question, data_version)

        if self._redis is not None:
            try:
                import json

                self._redis.setex(key, ttl_seconds, json.dumps(payload))
                return
            except Exception as exc:
                logger.warning("Redis set failed, falling back to memory: %s", exc)

        with self._lock:
            self._memory[key] = {
                "payload": payload,
                "expires_at": time.time() + ttl_seconds,
            }
