"""
rag/tracing.py
=======================
Lightweight tracing helpers with optional LangSmith/OpenTelemetry hooks.
"""

import logging
import os
import uuid
from typing import Dict

logger = logging.getLogger(__name__)


def start_trace(question: str) -> Dict[str, str]:
    trace_id = str(uuid.uuid4())
    provider = "none"

    if os.getenv("LANGSMITH_TRACING", "").strip().lower() in {"1", "true", "yes"}:
        provider = "langsmith"
    elif os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        provider = "opentelemetry"

    logger.info("Trace started (id=%s, provider=%s)", trace_id, provider)
    logger.debug("Trace question: %s", question)

    return {
        "trace_id": trace_id,
        "trace_provider": provider,
    }
