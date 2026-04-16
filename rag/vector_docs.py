"""
rag/vector_docs.py
===========================
Policy/manual document retrieval with vector-first, keyword fallback.
"""

import logging
import os
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
POLICY_DIR = BASE_DIR / "docs" / "policies"
CHROMA_DIR = BASE_DIR / ".rag" / "chroma"


class PolicyRetriever:
    def __init__(self) -> None:
        self._vector_ready = False
        self._keyword_docs: List[Dict[str, str]] = []
        self._vectorstore = None
        self._init_retriever()

    def _init_retriever(self) -> None:
        if not POLICY_DIR.exists():
            logger.info("Policy docs directory not found at %s", POLICY_DIR)
            return

        docs = []
        for path in POLICY_DIR.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                docs.append({"source": str(path.relative_to(BASE_DIR)), "text": text})

        self._keyword_docs = docs

        if not docs:
            return

        if os.getenv("ENABLE_VECTOR_RAG", "").strip().lower() not in {"1", "true", "yes"}:
            logger.info("ENABLE_VECTOR_RAG is disabled; using keyword docs retriever.")
            return

        try:
            from langchain_chroma import Chroma
            from langchain_core.documents import Document
            from langchain_openai import OpenAIEmbeddings
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=120)
            lc_docs = [Document(page_content=d["text"], metadata={"source": d["source"]}) for d in docs]
            chunks = splitter.split_documents(lc_docs)

            CHROMA_DIR.mkdir(parents=True, exist_ok=True)
            embeddings = OpenAIEmbeddings()
            self._vectorstore = Chroma.from_documents(
                documents=chunks,
                embedding=embeddings,
                persist_directory=str(CHROMA_DIR),
            )
            self._vector_ready = True
            logger.info("Vector policy retriever initialized with %d chunks.", len(chunks))
        except Exception as exc:
            logger.warning("Vector policy retriever unavailable (%s). Using keyword fallback.", exc)

    def retrieve(self, question: str, k: int = 3) -> List[Dict[str, str]]:
        question = question.strip()
        if not question:
            return []

        if self._vector_ready and self._vectorstore is not None:
            try:
                docs = self._vectorstore.similarity_search(question, k=k)
                return [
                    {
                        "id": f"D{i + 1}",
                        "source": str(doc.metadata.get("source", "unknown")),
                        "content": doc.page_content,
                    }
                    for i, doc in enumerate(docs)
                ]
            except Exception as exc:
                logger.warning("Vector retrieval failed, using keyword fallback: %s", exc)

        tokens = [t for t in question.lower().split() if len(t) > 2]
        scored = []
        for doc in self._keyword_docs:
            text_lower = doc["text"].lower()
            score = sum(1 for t in tokens if t in text_lower)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:k]

        results = []
        for i, (_, doc) in enumerate(top):
            results.append(
                {
                    "id": f"D{i + 1}",
                    "source": doc["source"],
                    "content": doc["text"][:900],
                }
            )

        return results
