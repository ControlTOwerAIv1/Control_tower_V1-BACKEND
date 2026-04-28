# QA Guide - KOL Distributor Toys AI Inventory Control Tower

## Running All Tests

```powershell
pytest tests/ -v
```

This runs the full test suite including service tests, endpoint tests, and memory tests.

## Running the Health Check

```powershell
python scripts/health_check.py
```

This checks environment variables, MySQL connectivity, table row counts, Claude API reachability, and FastAPI server status. Each check prints PASS or FAIL with a summary at the end.

## Test File Coverage

| Test File | Coverage |
|-----------|----------|
| `tests/test_avg_daily_sales.py` | Tests average daily sales calculation with zero sales, normal sales data, and missing product edge cases. |
| `tests/test_stockout.py` | Tests stockout prediction logic including zero-stock, lead-time comparisons, and division-by-zero handling. |
| `tests/test_reorder.py` | Tests reorder quantity formula, negative-result clamping to zero, and zero-average-sales edge case. |
| `tests/test_dead_inventory.py` | Tests dead inventory detection for products older than 60 days, within 60 days, never sold, and threshold validation. |
| `tests/test_chat_endpoint.py` | Tests the FastAPI `/api/chat` endpoint for valid responses, empty/whitespace rejection, error handling, and cache flag. |
| `tests/test_chat_engine.py` | Tests the Claude API wrapper for missing API key, empty inputs, response parsing, and non-text block handling. |
| `tests/test_memory.py` | Tests conversation memory for message appending, invalid roles, 20-message truncation, clearing, and prompt formatting. |

## Conversation Memory System

The chatbot maintains per-session conversation history in memory. Each session is identified by a `session_id` string.

### How It Works

- When a user sends a message, their question is stored in memory before being sent to Claude.
- Claude's response is also stored after it is received.
- On subsequent messages in the same session, the full conversation history is prepended to the system prompt so Claude has context of previous exchanges.
- History is capped at the last 20 messages per session to prevent unbounded memory growth.

### How the Frontend Should Use Session IDs

- Include a `session_id` field in the POST request body to `/api/chat`.
- Use a unique session ID per conversation thread (e.g., a UUID generated when the user starts a new chat).
- If no `session_id` is provided, the default value `"default"` is used (shared across all users without explicit sessions).
- To start a fresh conversation, either generate a new session ID or clear the existing one.

### Example Request

```json
{
    "question": "What products are at risk of stockout?",
    "session_id": "user-abc-session-1"
}
```

## Clearing a Session

Send a DELETE request to clear all conversation history for a session:

```
DELETE /api/chat/session/{session_id}
```

### Example

```powershell
curl -X DELETE http://127.0.0.1:8000/api/chat/session/user-abc-session-1
```

### Response

```json
{
    "cleared": true,
    "session_id": "user-abc-session-1"
}
```
