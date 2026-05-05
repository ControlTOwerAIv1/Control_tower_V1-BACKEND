"""
rag/llm_service.py
===========================
Centralized LLM service layer for provider/model switching.
"""

import logging
import os
from typing import Optional

from rag.chat_engine import call_claude, call_gemini

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = ("claude", "gemini", "openai")


def _validate_non_empty_string(value: str, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value).__name__}")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} must not be empty.")
    return cleaned


def _resolve_provider(provider: Optional[str] = None) -> str:
    value = provider if provider is not None else os.getenv("AI_PROVIDER", "")
    resolved = value.strip().lower()

    if not resolved:
        raise RuntimeError(
            "AI_PROVIDER environment variable is not set or is empty. "
            "Set it in .env before starting the application. "
            "Valid values: 'claude', 'gemini', or 'openai'."
        )

    if resolved not in _SUPPORTED_PROVIDERS:
        raise RuntimeError(
            f"AI_PROVIDER must be one of {_SUPPORTED_PROVIDERS}, got: {resolved}"
        )

    return resolved


def get_active_provider() -> str:
    return _resolve_provider()


def _get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} environment variable is not set or is empty. "
            "Set it in .env before starting the application."
        )
    return value


def _get_max_tokens() -> int:
    raw = _get_required_env("AI_MAX_TOKENS")
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"AI_MAX_TOKENS must be a valid integer, got: {raw}") from exc


def _get_openai_model() -> str:
    model = os.getenv("OPENAI_MODEL", "").strip() or os.getenv("AI_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "OPENAI_MODEL (or AI_MODEL) environment variable is not set or is empty. "
            "Set one of them in .env before starting the application."
        )
    return model


def _call_openai(context: str, question: str) -> str:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI API libraries not installed. Install openai: pip install openai"
        ) from exc

    context = _validate_non_empty_string(context, "context")
    question = _validate_non_empty_string(question, "question")

    api_key = _get_required_env("OPENAI_API_KEY")
    model = _get_openai_model()
    max_tokens = _get_max_tokens()

    logger.info("Calling OpenAI API (model=%s, max_tokens=%d) ...", model, max_tokens)

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": context},
                {"role": "user", "content": question},
            ],
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.error("OpenAI API error: %s", exc, exc_info=True)
        raise RuntimeError(f"OpenAI API error: {exc}") from exc

    if not response or not getattr(response, "choices", None):
        raise RuntimeError("OpenAI API returned no choices.")

    first_choice = response.choices[0]
    message = getattr(first_choice, "message", None)
    content = getattr(message, "content", None) if message is not None else None

    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI API returned an empty text response.")

    return content.strip()


def call_llm(context: str, question: str, provider: Optional[str] = None) -> str:
    selected_provider = _resolve_provider(provider)

    if selected_provider == "claude":
        return call_claude(context, question)
    if selected_provider == "gemini":
        return call_gemini(context, question)
    return _call_openai(context, question)
