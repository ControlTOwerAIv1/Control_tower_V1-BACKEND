"""
tests/test_chat_endpoint.py
=============================
Unit tests for routers/chat.py -- FastAPI chat endpoint.

Uses a clean FastAPI app with the chat router to avoid importing main.py
(which initializes the DB at import time).
"""

from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.chat import router

# Create a clean test app with just the chat router
_test_app = FastAPI()
_test_app.include_router(router)
client = TestClient(_test_app)


class TestChatEndpoint:
    """Tests for POST /api/chat."""

    @patch("routers.chat.is_cache_hit", return_value=False)
    @patch("routers.chat.route_query", return_value="This is a test answer.")
    def test_valid_question_returns_200(self, mock_route, mock_cache):
        """Valid POST with a question should return 200 with answer and from_cache."""
        response = client.post("/api/chat", json={"question": "test question"})
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert "from_cache" in data
        assert data["answer"] == "This is a test answer."

    def test_empty_question_returns_422(self):
        """Empty question should be rejected by Pydantic validation."""
        response = client.post("/api/chat", json={"question": ""})
        assert response.status_code == 422

    def test_whitespace_question_returns_422(self):
        """Whitespace-only question should be rejected by Pydantic validation."""
        response = client.post("/api/chat", json={"question": "   "})
        assert response.status_code == 422

    @patch("routers.chat.is_cache_hit", return_value=False)
    @patch("routers.chat.route_query", side_effect=RuntimeError("Claude is down"))
    def test_runtime_error_returns_500(self, mock_route, mock_cache):
        """RuntimeError from route_query should result in a 500 response."""
        response = client.post("/api/chat", json={"question": "test question"})
        assert response.status_code == 500
        assert "Failed to generate an answer" in response.json()["detail"]

    @patch("routers.chat.is_cache_hit", return_value=True)
    @patch("routers.chat.route_query", return_value="Cached answer.")
    def test_from_cache_true_when_cache_hit(self, mock_route, mock_cache):
        """from_cache should be True when is_cache_hit returns True."""
        response = client.post("/api/chat", json={"question": "cached question"})
        assert response.status_code == 200
        data = response.json()
        assert data["from_cache"] is True
