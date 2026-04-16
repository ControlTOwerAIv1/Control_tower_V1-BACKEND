"""Query router delegating to the LangGraph orchestrator pipeline."""

import logging

from rag.orchestrator import orchestrator

logger = logging.getLogger(__name__)


def is_cache_hit(question: str) -> bool:
    try:
        return orchestrator.is_cache_hit(question)
    except Exception as exc:
        logger.warning("Cache-hit check failed (non-fatal): %s", exc)
        return False


def route_query(question: str) -> str:
    try:
        result = orchestrator.ask(question)
        logger.info(
            "LangGraph route complete (from_cache=%s, data_version=%s, trace_id=%s)",
            result.from_cache,
            result.data_version,
            result.trace_id,
        )
        return result.answer
    except (TypeError, ValueError):
        raise
    except Exception as exc:
        logger.error("Orchestrator query routing failed: %s", exc, exc_info=True)
        raise RuntimeError(f"Cannot answer question: {exc}") from exc
