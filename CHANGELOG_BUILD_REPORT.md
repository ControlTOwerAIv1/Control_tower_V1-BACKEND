# KOL Distributor Toys AI Inventory Control Tower
# Build Report - Detailed Changes and Improvements

**Date:** April 27, 2026
**Project:** KOL Distributor Toys AI Inventory Control Tower
**Scope:** Defensive hardening, unit testing, conversation memory, agentic chatbot upgrade

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Section 1 - Defensive Hardening Script](#2-section-1---defensive-hardening-script)
3. [Section 2 - Unit Test Suite](#3-section-2---unit-test-suite)
4. [Section 3 - Conversation Memory System](#4-section-3---conversation-memory-system)
5. [Section 4 - Agentic Chatbot Upgrade](#5-section-4---agentic-chatbot-upgrade)
6. [Section 5 - Memory System Tests](#6-section-5---memory-system-tests)
7. [Section 6 - QA Documentation](#7-section-6---qa-documentation)
8. [Files Inventory](#8-files-inventory)
9. [Test Results](#9-test-results)
10. [Technical Constraints](#10-technical-constraints)

---

## 1. Executive Summary

This build delivers six major improvements to the KOL Distributor Toys AI Inventory Control Tower backend:

- **A production health check script** that validates every subsystem (environment, database, tables, Claude API, FastAPI server) with clear PASS/FAIL output.
- **A comprehensive unit test suite** with 49 automated tests covering all core services, the chat endpoint, and the AI engine -- all self-contained with no server dependency.
- **An in-memory conversation memory system** enabling multi-turn chatbot sessions with automatic history truncation.
- **An agentic chatbot upgrade** that injects conversation history into Claude's context, adds session management to the API, and deploys a new expert-level system prompt.
- **Full QA documentation** for developers and testers.

**Key metrics:**
- 13 new files created
- 3 existing files modified
- 49 unit tests, all passing
- Zero new dependencies added (pytest was already listed in requirements)
- Zero breaking changes to existing API contracts

---

## 2. Section 1 - Defensive Hardening Script

### File Created: `scripts/health_check.py`

**Purpose:** On-demand diagnostic tool that validates the full system stack is operational.

**What it checks (in order):**

| # | Check | How It Works |
|---|-------|-------------|
| 1 | `.env` + API Key | Loads `.env` from project root using `dotenv`, verifies `ANTHROPIC_API_KEY` is present and non-empty |
| 2 | MySQL Connection | Connects directly via `pymysql.connect()` using `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` from `.env` |
| 3 | Table Row Counts | Runs `SELECT COUNT(*) FROM <table>` for: `product`, `warehouse_product_management`, `invoice`, `invoice_details`, `lead_time_setting`. Each must have rows > 0 |
| 4 | Claude API | Creates an `anthropic.Anthropic` client and sends `"ping"` with `max_tokens=10`. Verifies a response is received |
| 5 | FastAPI Server | Sends a POST to `http://127.0.0.1:8000/api/chat` with `{"question": "test"}` using `urllib.request` (no external HTTP library) |

**Output format:**
- Each check prints `[PASS]` or `[FAIL]` with details
- Final summary: `SUMMARY: X passed, Y failed out of 5 checks`
- Exit code 0 if all pass, exit code 1 if any fail

**Usage:**
```powershell
python scripts/health_check.py
```

---

## 3. Section 2 - Unit Test Suite

### 3.1 Shared Fixtures: `tests/conftest.py`

Two reusable pytest fixtures available to all test files:

| Fixture | Returns |
|---------|---------|
| `mock_db_session` | A `MagicMock` SQLAlchemy session object |
| `sample_products` | List of 5 product dicts with keys: `id`, `name`, `current_stock`, `avg_daily_sales` |

---

### 3.2 `tests/test_avg_daily_sales.py` (6 tests)

**Tests the `get_avg_daily_sales` function and `_compute_avg` helper from `services/avg_daily_sales.py`.**

| Test | What It Validates |
|------|-------------------|
| `test_none_total_returns_zero` | `_compute_avg(None, 30)` returns `0.0` |
| `test_zero_total_returns_zero` | `_compute_avg(0, 30)` returns `0.0` |
| `test_normal_calculation` | `_compute_avg(150, 30)` returns `5.0` (total / days) |
| `test_zero_sales_rows_all_products_get_zero` | Mock DB returns 3 products but 0 sales rows; all get `avg = 0.0` |
| `test_sales_data_for_three_products` | Mock DB returns sales for 3 products; averages match `total / 30` |
| `test_product_with_no_matching_sales_defaults_to_zero` | Product present in DB but absent from sales query defaults to `0.0` |

**Mocking strategy:** Mocks `db.query()` to return product ID list and sales aggregation results separately.

---

### 3.3 `tests/test_stockout.py` (6 tests)

**Tests the `calculate_days_left` pure function from `services/stockout.py`.**

| Test | What It Validates |
|------|-------------------|
| `test_zero_stock_zero_sales_flagged_as_risk` | `stock=0, avg=0` returns `0.0` (flagged because `0 <= lead_time`) |
| `test_days_left_lte_lead_time_is_risk` | `stock=14, avg=2` gives `days_left=7`, equal to `lead_time=7` (at risk) |
| `test_days_left_gt_lead_time_not_risk` | `stock=100, avg=2` gives `days_left=50`, well above `lead_time=7` (safe) |
| `test_division_by_zero_handled_gracefully` | `stock=100, avg=0` returns `inf` (stock never depletes), does not raise |
| `test_negative_stock_clamped_to_zero` | Negative stock is treated as `0.0` days left |
| `test_both_zero_returns_zero` | Both zero: no-stock priority over no-sales |

**Mocking strategy:** No mocking needed -- `calculate_days_left` is a pure function.

---

### 3.4 `tests/test_reorder.py` (6 tests)

**Tests `calculate_reorder_quantity` and `calculate_reorder_point` from `services/reorder.py`.**

| Test | What It Validates |
|------|-------------------|
| `test_reorder_quantity_formula` | `(10 * (7 + 7)) - 50 = 90` matches expected output |
| `test_reorder_quantity_never_negative` | `(1 * 10) - 500 = -490` is clamped to `0.0` |
| `test_zero_avg_daily_sales_no_error` | `avg=0` does not raise, returns `0.0` |
| `test_zero_stock_gives_full_target` | `stock=0` means reorder qty equals full target `(5 * 14) = 70` |
| `test_basic_reorder_point` | `avg=5, lead_time=7` gives reorder point `35.0` |
| `test_zero_avg_gives_zero_point` | `avg=0` gives reorder point `0.0` |

---

### 3.5 `tests/test_dead_inventory.py` (8 tests)

**Tests `_days_since` helper and `get_dead_inventory` from `services/dead_inventory.py`.**

| Test | What It Validates |
|------|-------------------|
| `test_date_older_than_60_days` | Date 90 days ago returns `90` |
| `test_date_within_60_days` | Date 30 days ago returns `30` |
| `test_none_date_returns_none` | `None` (never sold) returns `None` |
| `test_today_returns_zero` | Today's date returns `0` |
| `test_product_older_than_60_days_flagged` | Product with last sale 90 days ago appears in dead list |
| `test_product_within_60_days_not_flagged` | Product with last sale 30 days ago does NOT appear |
| `test_product_never_sold_flagged` | Product with no sales record is flagged with `never_sold=True` |
| `test_threshold_is_60_days` | 59-day product is safe, 60-day product is flagged (boundary test) |

---

### 3.6 `tests/test_chat_endpoint.py` (5 tests)

**Tests the FastAPI `POST /api/chat` endpoint using `TestClient`.**

| Test | What It Validates |
|------|-------------------|
| `test_valid_question_returns_200` | Valid question returns 200 with `answer` and `from_cache` fields |
| `test_empty_question_returns_422` | Empty string `""` triggers Pydantic validation error (422) |
| `test_whitespace_question_returns_422` | Whitespace `"   "` triggers Pydantic validation error (422) |
| `test_runtime_error_returns_500` | `RuntimeError` from `route_query` becomes HTTP 500 |
| `test_from_cache_true_when_cache_hit` | `is_cache_hit` returning `True` sets `from_cache=True` in response |

**Mocking strategy:** Uses `unittest.mock.patch` on `routers.chat.route_query` and `routers.chat.is_cache_hit`. Creates a clean `FastAPI()` app with only the chat router to avoid DB initialization from `main.py`.

---

### 3.7 `tests/test_chat_engine.py` (8 tests)

**Tests `call_claude` and `parse_claude_response` from `ai/chat_engine.py`.**

| Test | What It Validates |
|------|-------------------|
| `test_raises_runtime_error_when_api_key_missing` | Empty `ANTHROPIC_API_KEY` env var raises `RuntimeError` |
| `test_raises_value_error_when_context_empty` | Empty context string raises `ValueError` |
| `test_raises_value_error_when_question_empty` | Empty question string raises `ValueError` |
| `test_raises_runtime_error_on_no_content` | Response with empty `content` list raises `RuntimeError` |
| `test_extracts_text_from_single_block` | Single text block correctly extracted |
| `test_skips_non_text_blocks_returns_text` | Image block skipped, text block returned |
| `test_raises_on_none_response` | `None` response raises `RuntimeError` |
| `test_raises_when_all_blocks_non_text` | All non-text blocks raises `RuntimeError` |

---

## 4. Section 3 - Conversation Memory System

### File Created: `ai/memory.py`

**Purpose:** In-memory conversation history store enabling multi-turn chatbot sessions.

**Architecture:**
- Storage: Module-level Python `dict` keyed by `session_id` (string)
- Thread safety: `threading.Lock` protects all read/write operations
- No external dependencies: no Redis, no database, no files
- Memory cap: 20 messages maximum per session (oldest messages trimmed automatically)

**Public API:**

| Function | Signature | Behavior |
|----------|-----------|----------|
| `add_message` | `(session_id: str, role: str, content: str) -> None` | Appends message. Validates role is `"user"` or `"assistant"`. Raises `ValueError` for invalid roles. Trims to last 20 messages. |
| `get_history` | `(session_id: str) -> list` | Returns copy of message list. Returns `[]` for unknown sessions. Never raises. |
| `clear_session` | `(session_id: str) -> None` | Deletes all history. No-op for unknown sessions. |
| `format_history_for_prompt` | `(session_id: str) -> str` | Formats as `"User: ..."` / `"Assistant: ..."` lines. Returns `""` if empty. |

**Message format stored:**
```python
{"role": "user", "content": "What products are at stockout risk?"}
```

---

## 5. Section 4 - Agentic Chatbot Upgrade

### 5.1 Modified: `ai/query_router.py`

**Changes made:**

1. **New import:** `from ai.memory import add_message, format_history_for_prompt`

2. **Signature change:** `route_query(question: str)` became `route_query(question: str, session_id: str = None)`

3. **Pre-Claude memory injection (new Step 3b):**
   - If `session_id` is not `None`, stores the user's question: `add_message(session_id, "user", question)`
   - Retrieves formatted conversation history via `format_history_for_prompt(session_id)`
   - If history is non-empty, prepends it to the context string:
     ```
     --- Conversation History ---
     User: previous question
     Assistant: previous answer
     --- End of History ---

     [original inventory context follows]
     ```

4. **Post-Claude memory storage (new in Step 6):**
   - If `session_id` is not `None`, stores Claude's answer: `add_message(session_id, "assistant", answer)`

5. **Error handling:** Both memory operations are wrapped in `try/except` -- memory failures are logged as warnings but never block the response.

---

### 5.2 Modified: `routers/chat.py`

**Changes made:**

1. **New import:** `from ai.memory import clear_session`

2. **ChatRequest model updated:**
   ```python
   class ChatRequest(BaseModel):
       question: str
       session_id: str = "default"    # <-- NEW FIELD
   ```

3. **route_query call updated:** Now passes `session_id`:
   ```python
   answer = await asyncio.get_event_loop().run_in_executor(
       None, partial(route_query, question, request.session_id)
   )
   ```

4. **New endpoint added:**
   ```
   DELETE /api/chat/session/{session_id}
   ```
   Calls `clear_session(session_id)` and returns:
   ```json
   {"cleared": true, "session_id": "the-session-id"}
   ```

---

### 5.3 Modified: `ai/chat_engine.py`

**Changes made:**

The `system` parameter in the `client.messages.create()` call was updated from a simple passthrough of the context string to a structured expert system prompt:

**Before:**
```python
system=context
```

**After:**
```python
system=(
    "You are an expert AI inventory analyst for KOL Distributor Toys.\n"
    "\n"
    "You have access to live inventory data including current stock levels, "
    "stockout risks, reorder recommendations, and dead inventory alerts.\n"
    "\n"
    "Your job is to give clear, direct, and actionable answers. "
    "When recommending reorders, always state the product name, current stock, "
    "recommended order quantity, and reason.\n"
    "When identifying risks, rank them by urgency.\n"
    "If you do not have enough data to answer, say so clearly.\n"
    "Never guess. Never fabricate product names or numbers.\n"
    "\n"
    + context
)
```

This gives Claude a clear expert persona and behavioral guidelines before the dynamic inventory data is injected.

**Also previously modified:** `timeout=30.0` was added to `anthropic.Anthropic()` constructor to prevent indefinite hangs.

---

## 6. Section 5 - Memory System Tests

### File Created: `tests/test_memory.py` (10 tests)

| Test | What It Validates |
|------|-------------------|
| `test_appends_to_history` | Single message correctly stored |
| `test_multiple_messages` | Three messages stored in order |
| `test_invalid_role_raises_value_error` | Role `"system"` raises `ValueError` |
| `test_history_truncated_to_20` | After 25 messages, only last 20 remain |
| `test_returns_empty_list_for_unknown_session` | Unknown session returns `[]` |
| `test_returns_copy` | Returned list is a copy, not internal reference |
| `test_removes_all_history` | `clear_session` empties the session |
| `test_no_error_for_unknown_session` | `clear_session` on unknown session does not raise |
| `test_returns_empty_string_for_empty_history` | Empty session returns `""` |
| `test_formats_messages_correctly` | Output uses `User:` and `Assistant:` prefixes |

Each test uses an `autouse` fixture that clears the memory store before and after to ensure isolation.

---

## 7. Section 6 - QA Documentation

### File Created: `README_QA.md`

**Contents:**
- How to run all tests: `pytest tests/ -v`
- How to run the health check: `python scripts/health_check.py`
- One-sentence description of what each test file covers
- How the conversation memory system works
- How session IDs should be used by the frontend
- How to clear a session: `DELETE /api/chat/session/{session_id}`
- Example request/response payloads

---

## 8. Files Inventory

### New Files Created (13)

| File | Lines | Purpose |
|------|-------|---------|
| `scripts/health_check.py` | 189 | Full system health diagnostic |
| `ai/memory.py` | 112 | In-memory conversation store |
| `tests/__init__.py` | 1 | Package marker |
| `tests/conftest.py` | 30 | Shared pytest fixtures |
| `tests/test_avg_daily_sales.py` | 86 | Avg daily sales tests |
| `tests/test_stockout.py` | 47 | Stockout prediction tests |
| `tests/test_reorder.py` | 66 | Reorder calculation tests |
| `tests/test_dead_inventory.py` | 103 | Dead inventory tests |
| `tests/test_chat_endpoint.py` | 58 | FastAPI endpoint tests |
| `tests/test_chat_engine.py` | 73 | Claude API wrapper tests |
| `tests/test_memory.py` | 95 | Memory system tests |
| `README_QA.md` | 82 | QA documentation |
| `CHANGELOG_BUILD_REPORT.md` | -- | This document |

### Existing Files Modified (3)

| File | Changes |
|------|---------|
| `ai/query_router.py` | Added `session_id` parameter, memory integration, history injection |
| `routers/chat.py` | Added `session_id` field, `DELETE` endpoint, memory import |
| `ai/chat_engine.py` | New expert system prompt, `timeout=30.0` on client |

---

## 9. Test Results

```
============================= test session starts =============================
platform win32 -- Python 3.11.0, pytest-9.0.3, pluggy-1.6.0

tests/test_avg_daily_sales.py    6 passed
tests/test_chat_endpoint.py      5 passed
tests/test_chat_engine.py        8 passed
tests/test_dead_inventory.py     8 passed
tests/test_memory.py            10 passed
tests/test_reorder.py            6 passed
tests/test_stockout.py           6 passed

============================= 49 passed in 1.37s ==============================
```

All 49 tests pass. All tests are self-contained and do not require the server, database, or Claude API to be running.

---

## 10. Technical Constraints

All constraints from the original requirements were verified and enforced:

| Constraint | Status |
|------------|--------|
| No em dashes anywhere | Verified via grep across all files |
| No LangChain or LangGraph | Not used |
| No new pip packages | Only `pytest` installed (already in requirements) |
| All imports at top of file | Verified in all 13 new files |
| All functions have docstrings | Verified in all new and modified code |
| Windows-compatible paths | Uses `pathlib.Path` throughout, no Unix assumptions |
| No external DB/Redis for memory | Uses plain Python `dict` with `threading.Lock` |

---

*End of Build Report*
