"""
rag/orchestrator.py
============================
LangGraph-based hybrid orchestrator for live SQL facts + policy docs.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, TypedDict

from sqlalchemy.orm import Session

from database import SessionLocal
from rag.cache_backend import VersionedResponseCache
from rag.data_version import compute_data_version
from rag.llm_service import call_llm, get_active_provider
from rag.sql_tools import (
    find_products_tool,
    get_dead_inventory_tool,
    get_inventory_summary_tool,
    get_reorder_recommendations_tool,
    get_stockout_risks_tool,
)
from rag.tracing import start_trace
from rag.vector_docs import PolicyRetriever

logger = logging.getLogger(__name__)

_MAX_QUESTION_LENGTH = 1000
_DEFAULT_TTL_SECONDS = int(os.getenv("RAG_RESPONSE_TTL_SECONDS", "900"))


class OrchestratorState(TypedDict, total=False):
    question: str
    intent: str
    sql_payload: Dict[str, Any]
    doc_payload: List[Dict[str, str]]
    citations: List[Dict[str, str]]
    answer: str
    trace_id: str


@dataclass
class OrchestratorResult:
    answer: str
    from_cache: bool
    data_version: str
    citations: List[Dict[str, str]]
    trace_id: str


class InventoryRAGOrchestrator:
    def __init__(self) -> None:
        self._policy_retriever = PolicyRetriever()
        self._cache = VersionedResponseCache()
        self._graph = self._build_graph()

    def _build_graph(self):
        try:
            from langgraph.graph import END, StateGraph
        except Exception as exc:
            logger.warning("LangGraph unavailable (%s). Falling back to sequential flow.", exc)
            return None

        graph = StateGraph(OrchestratorState)
        graph.add_node("classify", self._classify_node)
        graph.add_node("sql", self._sql_node)
        graph.add_node("docs", self._docs_node)
        graph.add_node("synthesize", self._synthesize_node)

        graph.set_entry_point("classify")

        def route_after_classify(state: OrchestratorState) -> str:
            intent = state.get("intent", "hybrid")
            if intent == "policy_docs":
                return "docs"
            if intent == "live_sql":
                return "sql"
            return "sql"

        graph.add_conditional_edges(
            "classify",
            route_after_classify,
            {
                "sql": "sql",
                "docs": "docs",
            },
        )

        graph.add_edge("sql", "docs")
        graph.add_edge("docs", "synthesize")
        graph.add_edge("synthesize", END)

        return graph.compile()

    @staticmethod
    def _classify_intent(question: str) -> str:
        q = question.lower()

        policy_tokens = {
            "policy",
            "sop",
            "manual",
            "guideline",
            "procedure",
            "playbook",
            "rule",
        }
        live_tokens = {
            "stock",
            "reorder",
            "inventory",
            "sku",
            "sales",
            "lead time",
            "stockout",
            "dead inventory",
            "product",
        }

        has_policy = any(t in q for t in policy_tokens)
        has_live = any(t in q for t in live_tokens)

        if has_policy and has_live:
            return "hybrid"
        if has_policy:
            return "policy_docs"
        return "live_sql"

    def _classify_node(self, state: OrchestratorState) -> OrchestratorState:
        intent = self._classify_intent(state["question"])
        return {"intent": intent}

    def _sql_node(self, state: OrchestratorState) -> OrchestratorState:
        if state.get("intent") == "policy_docs":
            return {"sql_payload": {}, "citations": []}

        question = state["question"]
        q_lower = question.lower()

        db: Session = SessionLocal()
        try:
            payload: Dict[str, Any] = {}
            citations: List[Dict[str, str]] = []

            summary = get_inventory_summary_tool(db)
            payload["summary"] = summary["summary"]
            citations.extend(summary["citations"])

            if "stockout" in q_lower or "out of stock" in q_lower:
                risks = get_stockout_risks_tool(db)
                payload.update(risks)
                citations.extend(risks.get("citations", []))

            if "reorder" in q_lower or "order" in q_lower:
                recs = get_reorder_recommendations_tool(db)
                payload.update(recs)
                citations.extend(recs.get("citations", []))

            if "dead" in q_lower or "slow" in q_lower:
                dead = get_dead_inventory_tool(db)
                payload.update(dead)
                citations.extend(dead.get("citations", []))

            # Product-level fallback extraction for specific product mentions.
            if "product" in q_lower or "sku" in q_lower:
                product_hits = find_products_tool(db, query=question)
                payload.update(product_hits)
                citations.extend(product_hits.get("citations", []))

            return {
                "sql_payload": payload,
                "citations": citations,
            }
        finally:
            db.close()

    def _docs_node(self, state: OrchestratorState) -> OrchestratorState:
        intent = state.get("intent", "live_sql")
        if intent == "live_sql":
            return {"doc_payload": []}

        docs = self._policy_retriever.retrieve(state["question"], k=3)
        return {"doc_payload": docs}

    def _synthesize_node(self, state: OrchestratorState) -> OrchestratorState:
        provider = get_active_provider()
        question = state["question"]
        sql_payload = state.get("sql_payload", {})
        doc_payload = state.get("doc_payload", [])
        citations = state.get("citations", []).copy()

        if doc_payload:
            for doc in doc_payload:
                citations.append({"id": doc["id"], "source": doc["source"]})

        context = (
            "You are an inventory assistant.\n"
            "Answer using live SQL facts and policy docs below.\n"
            "If a value is missing, explicitly say data is not available.\n"
            "Cite sources in square brackets like [S1] or [D1].\n\n"
            f"INTENT: {state.get('intent', 'live_sql')}\n"
            f"SQL_PAYLOAD: {sql_payload}\n"
            f"DOC_PAYLOAD: {doc_payload}\n"
            f"CITATIONS: {citations}\n"
        )

        answer = call_llm(context, question, provider=provider)

        # Guarantee citations visibility even if model omits them.
        if citations:
            citation_line = "\n\nSources: " + ", ".join(
                f"{c['id']}={c['source']}" for c in citations
            )
            if "Sources:" not in answer:
                answer += citation_line

        return {
            "answer": answer,
            "citations": citations,
        }

    def _run_flow(self, question: str) -> OrchestratorState:
        start = {
            "question": question,
        }

        if self._graph is not None:
            return self._graph.invoke(start)

        # Sequential fallback when LangGraph is unavailable.
        state = start.copy()
        state.update(self._classify_node(state))
        state.update(self._sql_node(state))
        state.update(self._docs_node(state))
        state.update(self._synthesize_node(state))
        return state

    def ask(self, question: str) -> OrchestratorResult:
        if not isinstance(question, str):
            raise TypeError(f"question must be a string, got {type(question).__name__}")

        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty or whitespace-only.")

        if len(question) > _MAX_QUESTION_LENGTH:
            question = question[:_MAX_QUESTION_LENGTH]

        trace = start_trace(question)

        db: Session = SessionLocal()
        try:
            data_version = compute_data_version(db)
        finally:
            db.close()

        cached = self._cache.get(question, data_version)
        if cached is not None:
            return OrchestratorResult(
                answer=cached.get("answer", ""),
                from_cache=True,
                data_version=data_version,
                citations=cached.get("citations", []),
                trace_id=trace["trace_id"],
            )

        result_state = self._run_flow(question)
        answer = result_state.get("answer", "").strip()
        citations = result_state.get("citations", [])

        if not answer:
            raise RuntimeError("Orchestrator produced an empty answer.")

        self._cache.set(
            question=question,
            data_version=data_version,
            payload={
                "answer": answer,
                "citations": citations,
            },
            ttl_seconds=_DEFAULT_TTL_SECONDS,
        )

        return OrchestratorResult(
            answer=answer,
            from_cache=False,
            data_version=data_version,
            citations=citations,
            trace_id=trace["trace_id"],
        )

    def is_cache_hit(self, question: str) -> bool:
        if not isinstance(question, str) or not question.strip():
            return False

        db: Session = SessionLocal()
        try:
            data_version = compute_data_version(db)
        finally:
            db.close()

        cached = self._cache.get(question, data_version)
        return cached is not None


orchestrator = InventoryRAGOrchestrator()
