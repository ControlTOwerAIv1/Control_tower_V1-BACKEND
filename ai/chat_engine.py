"""
ai/chat_engine.py
==================
The ONLY file in the system that calls the Claude API.

It receives a pre-built context string and the user's question, builds the
full API payload, calls Claude, and returns the response text.

Edge cases handled:
    - API key missing from environment → raises RuntimeError at call time
    - Empty context or question → raises ValueError
    - API rate limit (HTTP 429) → caught and re-raised with descriptive message
    - API timeout → caught and re-raised
    - Malformed response structure → parsed safely with fallback
    - Empty content blocks in response → raises RuntimeError
    - Non-text content blocks → skipped gracefully

Input validations:
    - context must be a non-empty string
    - question must be a non-empty string
    - API key must be loaded from ANTHROPIC_API_KEY environment variable

Assumptions NOT made:
    - Not assuming the API always returns valid JSON
    - Not assuming content always has type "text"
    - Not assuming network is always available
    - Not assuming the API key is always present
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
# Configuration (loaded from environment — never hardcoded)
# ---------------------------------------------------------------------------

def _get_claude_model() -> str:
    """Load Claude model from environment."""
    model = os.getenv("CLAUDE_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "CLAUDE_MODEL environment variable is not set or is empty. "
            "Set it in .env before starting the application."
        )
    return model


def _get_gemini_model() -> str:
    """Load Gemini model from environment."""
    model = os.getenv("GEMINI_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "GEMINI_MODEL environment variable is not set or is empty. "
            "Set it in .env before starting the application."
        )
    return model


def _get_max_tokens() -> int:
    """Load max tokens from environment."""
    try:
        tokens = os.getenv("AI_MAX_TOKENS", "").strip()
        if not tokens:
            raise RuntimeError(
                "AI_MAX_TOKENS environment variable is not set or is empty. "
                "Set it in .env before starting the application."
            )
        return int(tokens)
    except ValueError:
        raise RuntimeError(
            f"AI_MAX_TOKENS must be a valid integer, got: {tokens}"
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_non_empty_string(value: str, name: str) -> str:
    """
    Validate that a value is a non-empty string.

    Args:
        value: The value to validate.
        name: The parameter name for error messages.

    Returns:
        The stripped string.

    Raises:
        TypeError: If value is not a string.
        ValueError: If value is empty after stripping.
    """
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{name} must not be empty.")
    return stripped


def _get_api_key() -> str:
    """
    Load the Anthropic API key from the environment.

    Returns:
        The API key string.

    Raises:
        RuntimeError: If ANTHROPIC_API_KEY is not set or empty.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set or is empty. "
            "Set it before starting the application."
        )
    return api_key


def _get_gemini_api_key() -> str:
    """
    Load the Gemini API key from the environment.

    Returns:
        The API key string.

    Raises:
        RuntimeError: If GEMINI_API_KEY is not set or empty.
    """
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
    """
    Build the messages list for the Claude API call.

    The system prompt is set separately (not in messages).  The user
    message carries the question.

    Args:
        context: The pre-built context string (used as system prompt).
        question: The user's question.

    Returns:
        A list of message dicts suitable for the Anthropic API.

    Raises:
        TypeError: If either argument is not a string.
        ValueError: If either argument is empty.
    """
    context = _validate_non_empty_string(context, "context")
    question = _validate_non_empty_string(question, "question")

    return [
        {"role": "user", "content": question},
    ]


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def parse_claude_response(response: Any) -> str:
    """
    Extract plain text from a Claude API response.

    Iterates over content blocks and concatenates all blocks of type "text".
    Non-text blocks are skipped with a debug log.

    Args:
        response: The full API response object from Anthropic.

    Returns:
        The concatenated text content as a clean string.

    Raises:
        RuntimeError: If the response is None, has no content, or contains
                      no text blocks.
    """
    if response is None:
        raise RuntimeError("Claude API returned None response.")

    # The Anthropic SDK returns an object with a .content attribute
    content_blocks = getattr(response, "content", None)

    if content_blocks is None:
        raise RuntimeError(
            "Claude API response has no 'content' attribute."
        )

    if not content_blocks:
        raise RuntimeError(
            "Claude API response content is empty (no content blocks)."
        )

    text_parts: List[str] = []

    for block in content_blocks:
        block_type = getattr(block, "type", None)

        if block_type == "text":
            text_value = getattr(block, "text", "")
            if text_value:
                text_parts.append(text_value)
        else:
            logger.debug(
                "Skipping non-text content block of type: %s", block_type
            )

    if not text_parts:
        raise RuntimeError(
            "Claude API response contained content blocks but none of type 'text'."
        )

    result = "\n".join(text_parts).strip()

    if not result:
        raise RuntimeError("Claude API returned an empty text response.")

    return result


# ---------------------------------------------------------------------------
# Gemini response parser
# ---------------------------------------------------------------------------

def parse_gemini_response(response: Any) -> str:
    """
    Extract plain text from a Gemini API response.

    Args:
        response: The full API response object from Gemini.

    Returns:
        The text content as a clean string.

    Raises:
        RuntimeError: If the response is None, has no candidates, or contains
                      no valid text blocks.
    """
    if response is None:
        raise RuntimeError("Gemini API returned None response.")

    # Gemini returns a GenerateContentResponse with candidates list
    candidates = getattr(response, "candidates", None)

    if not candidates:
        raise RuntimeError(
            "Gemini API response has no candidates."
        )

    # Get the first candidate
    candidate = candidates[0]
    content = getattr(candidate, "content", None)

    if content is None:
        raise RuntimeError(
            "Gemini API candidate has no 'content' attribute."
        )

    # Extract text parts from candidate content
    parts = getattr(content, "parts", None)
    if not parts:
        raise RuntimeError(
            "Gemini API response content has no parts."
        )

    text_parts: List[str] = []
    for part in parts:
        text_value = getattr(part, "text", None)
        if text_value:
            text_parts.append(text_value)

    if not text_parts:
        raise RuntimeError(
            "Gemini API response contained parts but none with text."
        )

    result = "\n".join(text_parts).strip()

    if not result:
        raise RuntimeError("Gemini API returned an empty text response.")

    return result


# ---------------------------------------------------------------------------
# Main API call
# ---------------------------------------------------------------------------

def call_claude(context: str, question: str) -> str:
    """
    Call the Claude API with the pre-built context and user question.

    Args:
        context: The structured context string from context_builder
                 (injected as the system prompt).
        question: The user's question.

    Returns:
        The text response from Claude.

    Raises:
        TypeError: If context or question is not a string.
        ValueError: If context or question is empty.
        RuntimeError: If the API key is missing, the API call fails,
                      or the response is malformed.
    """
    context = _validate_non_empty_string(context, "context")
    question = _validate_non_empty_string(question, "question")

    api_key = _get_api_key()
    messages = build_messages_payload(context, question)

    claude_model = _get_claude_model()
    max_tokens = _get_max_tokens()
    logger.info(
        "Calling Claude API (model=%s, max_tokens=%d) …", claude_model, max_tokens
    )

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
        raise RuntimeError(
            "Claude API rate limit exceeded. Please try again later."
        ) from exc

    except anthropic.APITimeoutError as exc:
        logger.error("Claude API request timed out: %s", exc)
        raise RuntimeError(
            "Claude API request timed out. Please try again later."
        ) from exc

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
        raise RuntimeError(
            f"Unexpected error calling Claude API: {exc}"
        ) from exc

    # Parse and return
    answer = parse_claude_response(response)
    logger.info("Claude responded with %d characters.", len(answer))
    return answer


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------

def call_gemini(context: str, question: str) -> str:
    """
    Call the Gemini API with the pre-built context and user question.

    Args:
        context: The structured context string from context_builder
                 (injected as the system prompt).
        question: The user's question.

    Returns:
        The text response from Gemini.

    Raises:
        TypeError: If context or question is not a string.
        ValueError: If context or question is empty.
        RuntimeError: If the API key is missing, the API call fails,
                      or the response is malformed.
    """
    genai = _ensure_gemini_available()

    context = _validate_non_empty_string(context, "context")
    question = _validate_non_empty_string(question, "question")

    api_key = _get_gemini_api_key()

    gemini_model = _get_gemini_model()
    max_tokens = _get_max_tokens()
    logger.info(
        "Calling Gemini API (model=%s, max_tokens=%d) …", gemini_model, max_tokens
    )

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(gemini_model)

        # Build the full prompt with context as system instruction
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

    # Parse and return
    answer = parse_gemini_response(response)
    logger.info("Gemini responded with %d characters.", len(answer))
    return answer
