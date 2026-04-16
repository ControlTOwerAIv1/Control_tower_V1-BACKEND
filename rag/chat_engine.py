"""
rag/chat_engine.py
===========================
Provider-specific LLM API call helpers used by the RAG query pipeline.
"""

import logging
import os
from typing import Any, Dict, List

import anthropic

logger = logging.getLogger(__name__)


def _ensure_gemini_available():
    """Attempt to import Gemini library and raise error if unavailable."""
    try:
        import google.generativeai as genai
        return genai
    except ImportError as exc:
        raise RuntimeError(
            "Gemini API libraries not installed. "
            "Install google-generativeai: pip install google-generativeai"
        ) from exc


# ---------------------------------------------------------------------------
# Configuration (loaded from environment; never hardcoded)
# ---------------------------------------------------------------------------

def _get_claude_model() -> str:
    model = os.getenv("CLAUDE_MODEL", "").strip() or os.getenv("AI_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "CLAUDE_MODEL (or AI_MODEL) environment variable is not set or is empty. "
            "Set one of them in .env before starting the application."
        )
    return model


def _get_gemini_model() -> str:
    model = os.getenv("GEMINI_MODEL", "").strip() or os.getenv("AI_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "GEMINI_MODEL (or AI_MODEL) environment variable is not set or is empty. "
            "Set one of them in .env before starting the application."
        )
    return model


def _get_max_tokens() -> int:
    try:
        tokens = os.getenv("AI_MAX_TOKENS", "").strip()
        if not tokens:
            raise RuntimeError(
                "AI_MAX_TOKENS environment variable is not set or is empty. "
                "Set it in .env before starting the application."
            )
        return int(tokens)
    except ValueError as exc:
        raise RuntimeError(f"AI_MAX_TOKENS must be a valid integer, got: {tokens}") from exc


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_non_empty_string(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{name} must not be empty.")
    return stripped


def _get_api_key() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set or is empty. "
            "Set it before starting the application."
        )
    return api_key


def _get_gemini_api_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set or is empty. "
            "Set it before starting the application."
        )
    return api_key


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------

def build_messages_payload(context: str, question: str) -> List[Dict[str, str]]:
    context = _validate_non_empty_string(context, "context")
    question = _validate_non_empty_string(question, "question")
    return [{"role": "user", "content": question}]


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def parse_claude_response(response: Any) -> str:
    if response is None:
        raise RuntimeError("Claude API returned None response.")

    content_blocks = getattr(response, "content", None)
    if content_blocks is None:
        raise RuntimeError("Claude API response has no 'content' attribute.")
    if not content_blocks:
        raise RuntimeError("Claude API response content is empty (no content blocks).")

    text_parts: List[str] = []
    for block in content_blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_value = getattr(block, "text", "")
            if text_value:
                text_parts.append(text_value)
        else:
            logger.debug("Skipping non-text content block of type: %s", block_type)

    if not text_parts:
        raise RuntimeError(
            "Claude API response contained content blocks but none of type 'text'."
        )

    result = "\n".join(text_parts).strip()
    if not result:
        raise RuntimeError("Claude API returned an empty text response.")
    return result


def parse_gemini_response(response: Any) -> str:
    if response is None:
        raise RuntimeError("Gemini API returned None response.")

    candidates = getattr(response, "candidates", None)
    if not candidates:
        raise RuntimeError("Gemini API response has no candidates.")

    candidate = candidates[0]
    content = getattr(candidate, "content", None)
    if content is None:
        raise RuntimeError("Gemini API candidate has no 'content' attribute.")

    parts = getattr(content, "parts", None)
    if not parts:
        raise RuntimeError("Gemini API response content has no parts.")

    text_parts: List[str] = []
    for part in parts:
        text_value = getattr(part, "text", None)
        if text_value:
            text_parts.append(text_value)

    if not text_parts:
        raise RuntimeError("Gemini API response contained parts but none with text.")

    result = "\n".join(text_parts).strip()
    if not result:
        raise RuntimeError("Gemini API returned an empty text response.")
    return result


# ---------------------------------------------------------------------------
# Provider call functions
# ---------------------------------------------------------------------------

def call_claude(context: str, question: str) -> str:
    context = _validate_non_empty_string(context, "context")
    question = _validate_non_empty_string(question, "question")

    api_key = _get_api_key()
    messages = build_messages_payload(context, question)
    claude_model = _get_claude_model()
    max_tokens = _get_max_tokens()

    logger.info("Calling Claude API (model=%s, max_tokens=%d) ...", claude_model, max_tokens)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=claude_model,
            max_tokens=max_tokens,
            system=context,
            messages=messages,
        )
    except anthropic.RateLimitError as exc:
        logger.error("Claude API rate limit exceeded: %s", exc)
        raise RuntimeError("Claude API rate limit exceeded. Please try again later.") from exc
    except anthropic.APITimeoutError as exc:
        logger.error("Claude API request timed out: %s", exc)
        raise RuntimeError("Claude API request timed out. Please try again later.") from exc
    except anthropic.AuthenticationError as exc:
        logger.error("Claude API authentication failed: %s", exc)
        raise RuntimeError(
            "Claude API authentication failed. Check your ANTHROPIC_API_KEY."
        ) from exc
    except anthropic.APIError as exc:
        logger.error("Claude API error: %s", exc)
        raise RuntimeError(f"Claude API error: {exc}") from exc
    except Exception as exc:
        logger.error("Unexpected error calling Claude API: %s", exc, exc_info=True)
        raise RuntimeError(f"Unexpected error calling Claude API: {exc}") from exc

    answer = parse_claude_response(response)
    logger.info("Claude responded with %d characters.", len(answer))
    return answer


def call_gemini(context: str, question: str) -> str:
    genai = _ensure_gemini_available()

    context = _validate_non_empty_string(context, "context")
    question = _validate_non_empty_string(question, "question")

    api_key = _get_gemini_api_key()
    gemini_model = _get_gemini_model()
    max_tokens = _get_max_tokens()

    logger.info("Calling Gemini API (model=%s, max_tokens=%d) ...", gemini_model, max_tokens)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(gemini_model)
        full_prompt = f"{context}\n\nUser Question: {question}"
        response = model.generate_content(
            full_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
            ),
        )
    except Exception as exc:
        logger.error("Gemini API error: %s", exc, exc_info=True)
        raise RuntimeError(f"Gemini API error: {exc}") from exc

    answer = parse_gemini_response(response)
    logger.info("Gemini responded with %d characters.", len(answer))
    return answer
