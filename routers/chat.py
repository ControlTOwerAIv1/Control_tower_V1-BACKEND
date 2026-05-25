"""
routers/chat.py
================
FastAPI router exposing the chatbot endpoint.

Edge cases handled:
    - Empty question → returns 400 Bad Request
    - Whitespace-only question → returns 400 Bad Request
    - Claude API fails → returns 500 with descriptive message
    - Cache hit → response includes from_cache = True
    - Very long question → truncated by query_router (transparent to caller)
    - Missing question field in body → Pydantic validation catches it

Input validations:
    - Request body must contain a non-empty "question" string

Assumptions NOT made:
    - Not assuming Claude is always reachable
    - Not assuming query_router always succeeds
    - Not assuming the answer is always non-empty
"""

import asyncio
import logging
from functools import partial
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ai.memory import clear_session
from ai.query_router import is_cache_hit, route_query, _is_sql_question
from ai.sql_agent import run_sql_agent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Chat"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""

    question: str
    session_id: str = "default"

    @field_validator("question")
    @classmethod
    def question_must_not_be_empty(cls, v: str) -> str:
        """Validate that the question is not empty or whitespace-only."""
        if not isinstance(v, str) or not v.strip():
            raise ValueError("question must be a non-empty string.")
        return v.strip()


class ChatResponse(BaseModel):
    """Response body for the chat endpoint."""

    answer: str
    from_cache: bool
    type: str = "text"
    data: Optional[list] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> Dict[str, Any]:
    """
    Accept a user question and return an AI-generated answer.

    Routes to SQL agent for data/query questions.
    Routes to RAG cache -> Claude pipeline for general questions.

    Args:
        request: ChatRequest with a non-empty question string.

    Returns:
        Dict with 'answer', 'from_cache', 'type', and 'data'.

    Raises:
        HTTPException: 400 if the question is invalid,
                       500 if the pipeline fails.
    """
    question = request.question

    # --- SQL Agent path ---
    if _is_sql_question(question):
        logger.info("Routing to SQL agent: %s", question)
        try:
            result = await run_sql_agent(question)
        except Exception as exc:
            logger.error("SQL agent error: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"SQL agent failed: {exc}",
            ) from exc

        if result["type"] == "error":
            raise HTTPException(
                status_code=500,
                detail=result["content"],
            )

        logger.info(
            "SQL agent response returned (type=%s, answer_len=%d).",
            result["type"],
            len(result["content"]),
        )

        return {
            "answer": result["content"],
            "from_cache": False,
            "type": result["type"],
            "data": result.get("data"),
        }

    # --- RAG cache -> Claude path (existing logic, unchanged) ---
    was_cached = is_cache_hit(question)

    try:
        answer = await asyncio.get_event_loop().run_in_executor(
            None, partial(route_query, question, request.session_id)
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Chat request rejected: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid question: {exc}",
        ) from exc
    except RuntimeError as exc:
        logger.error("Chat pipeline error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate an answer: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Unexpected chat error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing your question.",
        ) from exc

    logger.info(
        "Chat response returned (from_cache=%s, answer_len=%d).",
        was_cached,
        len(answer),
    )

    return {
        "answer": answer,
        "from_cache": was_cached,
        "type": "text",
        "data": None,
    }


@router.delete("/chat/session/{session_id}")
async def clear_chat_session(session_id: str) -> dict:
    """
    Clear all conversation history for the given session.

    Args:
        session_id: The session identifier to clear.

    Returns:
        Dict confirming the session was cleared.
    """
    clear_session(session_id)
    logger.info("Cleared chat session: %s", session_id)
    return {"cleared": True, "session_id": session_id}
