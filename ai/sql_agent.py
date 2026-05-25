# ===========================================================================
# ai/sql_agent.py
# Multi-step SQL Agent pipeline using LangChain
# ===========================================================================
# Required pip installs (run before starting server):
# pip install langchain langchain-community langgraph "langchain[anthropic]" --break-system-packages
# ===========================================================================

import os
import json
import logging
import asyncio
from typing import Any

from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level state -- lazy initialization (never initialized at import time)
# ---------------------------------------------------------------------------
_db: Any = None
_agent: Any = None


# ---------------------------------------------------------------------------
# FUNCTION 1: _get_agent()  (private, synchronous)
# ---------------------------------------------------------------------------
def _get_agent() -> Any:
    """Initialize and cache the LangChain SQL agent on first call.
    Return the cached agent on subsequent calls.
    """
    global _db, _agent

    # Cache hit — return immediately
    if _agent is not None:
        return _agent

    # ---- Read DB connection details from environment ----
    db_host = os.getenv("DB_HOST", "localhost").strip()
    db_port = os.getenv("DB_PORT", "3306").strip()
    db_name = os.getenv("DB_NAME", "").strip()
    db_user = os.getenv("DB_USER", "root").strip()
    db_password = os.getenv("DB_PASSWORD", "").strip()

    if not db_name:
        raise RuntimeError("DB_NAME environment variable is not set.")

    db_url = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    # ---- Read ANTHROPIC_API_KEY from environment ----
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set.")

    # LangChain Anthropic integration reads the key from env
    os.environ["ANTHROPIC_API_KEY"] = api_key

    # ---- Initialize database connection ----
    _db = SQLDatabase.from_uri(db_url)
    logger.info(f"SQL Agent connected to database. Tables: {_db.get_usable_table_names()}")

    # ---- Initialize LLM ----
    model = init_chat_model("claude-sonnet-4-6", model_provider="anthropic")

    # ---- Initialize toolkit and extract tools ----
    toolkit = SQLDatabaseToolkit(db=_db, llm=model)
    tools = toolkit.get_tools()

    for tool in tools:
        logger.debug(f"Tool discovered: {tool.name} — {tool.description}")

    # ---- System prompt ----
    SYSTEM_PROMPT = """You are a precise SQL query agent for KOL Distributor Toys inventory system.
Your job is to answer the user's inventory question by querying a live MySQL database.

You must always follow this exact sequence of steps. Never skip a step.

STEP 1 — SCHEMA RETRIEVAL (always do this first, every time):
   Call sql_db_list_tables to see all available tables.
   Then call sql_db_schema on the tables that are likely relevant to the question.
   Read the column names and types carefully. Never assume column names.

STEP 2 — SQL GENERATION:
   Write a syntactically correct MySQL SELECT query based only on what
   schema retrieval returned. Never use column names that were not in the schema output.
   
   Critical schema facts (verified against live database):
   - Primary key for products is "id", NOT "product_id"
   - Sales data is in tables "invoice" and "invoice_details", NOT "sales_bill" or "sales_bill_details"
   - Stock quantity column is "qty", NOT "quantity"
   - lead_time_setting stores days as VARCHAR with no product_id column
   - Use only SELECT statements. Never write INSERT, UPDATE, DELETE, or DROP.
   - For any sales-related query, default to the last 30 days unless the user specifies otherwise.

STEP 3 — SQL VALIDATION (always do this before executing):
   Pass your generated query to sql_db_query_checker.
   Read the checker's output carefully.
   If it reports any issue, fix the query and check again before proceeding.
   Do not execute a query that has not passed the checker.

STEP 4 — EXECUTE QUERY:
   Call sql_db_query with the validated query.
   If the database returns an error instead of rows:
     - Read the error message carefully
     - Identify what went wrong (wrong column name, wrong table, syntax error)
     - Fix the query
     - Go back to Step 3 (validate the fix before re-executing)
     - Retry until you get rows or determine the question cannot be answered

STEP 5 — FORMAT AND RETURN:
   Once you have query results, format your final response as follows:

   IF the user asked for a "chart", "graph", "bar chart", "bar graph", or "visualize":
      Return ONLY a JSON array. Each item must have exactly two keys:
      "label" (string, the product name or category) and "value" (number).
      Example: [{"label": "Product A", "value": 120}, {"label": "Product B", "value": 85}]
      Return absolutely nothing outside this JSON array — no explanation, no prose.

   IF the result contains multiple rows comparing items (a list, ranking, or comparison):
      Format as a clean markdown table with aligned columns using | separators.
      Add a one-sentence plain English summary below the table.

   IF the result is a single value or a short factual answer:
      Answer in plain English. State the exact number. Be concise.

   IN ALL CASES:
      Never fabricate product names or numbers.
      If the query returned no rows, say clearly: "No data found for this query."
      If you could not write a valid query after retrying, explain why."""

    # ---- Initialize the agent ----
    _agent = create_agent(
        model,
        tools,
        system_prompt=SYSTEM_PROMPT,
    )

    logger.info("SQL Agent initialized successfully.")

    return _agent


# ---------------------------------------------------------------------------
# FUNCTION 2: _detect_output_type()  (private, synchronous)
# ---------------------------------------------------------------------------
def _detect_output_type(answer: str) -> dict:
    """Parse the agent's string output and return a structured dict."""
    answer = answer.strip()

    # ---- Try to parse as JSON array (chart output) ----
    cleaned = answer.strip()
    if cleaned.startswith("["):
        try:
            parsed = json.loads(cleaned)
            if (
                isinstance(parsed, list)
                and all(
                    isinstance(item, dict)
                    and "label" in item
                    and "value" in item
                    for item in parsed
                )
            ):
                return {"type": "chart", "content": answer, "data": parsed}
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

    # ---- Check for markdown table (table output) ----
    if "| " in answer and " |" in answer and "\n" in answer:
        return {"type": "table", "content": answer, "data": None}

    # ---- Default to plain text ----
    return {"type": "text", "content": answer, "data": None}


# ---------------------------------------------------------------------------
# FUNCTION 3: run_sql_agent()  (PUBLIC, async)
# ---------------------------------------------------------------------------
async def run_sql_agent(question: str) -> dict:
    """The single public entry point called by query_router.py.
    Accepts a user question, runs the full agent pipeline,
    returns a typed dict ready for the FastAPI response.
    """
    try:
        # ---- Validate input ----
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        question = question.strip()

        logger.info(f"SQL Agent received question: {question}")

        # ---- Get the agent ----
        agent = _get_agent()

        # ---- Run the agent asynchronously (graph.invoke is sync) ----
        def _invoke():
            result = agent.invoke(
                {"messages": [{"role": "user", "content": question}]}
            )
            # Extract the last AI message content from the result
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if hasattr(msg, "content") and msg.content:
                    return msg.content
            return "No response generated."

        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, _invoke)

        logger.info(f"SQL Agent completed. Response length: {len(answer)} chars")

        # ---- Detect output type and return ----
        return _detect_output_type(answer)

    except Exception as exc:
        logger.error(f"SQL Agent failed: {exc}", exc_info=True)
        return {"type": "error", "content": str(exc), "data": None}
