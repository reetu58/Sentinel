"""Retrieval over the governance corpus — citations with every result.

WHY HAYSTACK (and BM25 specifically):
- The spec says "Haystack OR RAGFlow; pick one." Haystack is a pip-only Python
  library — no separate server to run, which fits a solo, locally-verifiable
  build. RAGFlow is a full containerized service (its own API, DB, web UI);
  that's more infrastructure than this prototype needs.
- We use Haystack's in-memory **BM25** retriever rather than dense embeddings
  on purpose: it needs no embedding-model API key, is deterministic, and runs
  anywhere — so retrieval (and the agents that depend on it) can be verified
  offline. The corpus is small (a handful of governance docs), where lexical
  retrieval is strong. Swapping in an embedding retriever later is a localized
  change behind this same `Retriever` interface.

Crucially, retrieval NEVER returns bare text: every hit is a `Citation`
carrying its `doc:section` id, so the Investigator/Drafter physically cannot
cite something the corpus doesn't contain.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from haystack import Document
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
from haystack.document_stores.in_memory import InMemoryDocumentStore

from . import config
from .corpus import Chunk, load_corpus


@dataclass(frozen=True)
class Citation:
    """A retrieved passage with its canonical citation."""

    doc_id: str
    doc_title: str
    section_id: str
    section_title: str
    text: str
    score: float

    @property
    def citation(self) -> str:
        return f"{self.doc_id}:{self.section_id}"

    def short(self, width: int = 220) -> str:
        body = " ".join(self.text.split())
        snippet = body if len(body) <= width else body[:width] + "…"
        return f"[{self.citation}] {snippet}"


class Retriever:
    """BM25 retrieval over the governance corpus, returning `Citation`s."""

    def __init__(self, store: InMemoryDocumentStore):
        self._store = store
        self._bm25 = InMemoryBM25Retriever(document_store=store)

    @classmethod
    def from_chunks(cls, chunks: list[Chunk]) -> "Retriever":
        store = InMemoryDocumentStore()
        store.write_documents(
            [
                Document(
                    content=c.text,
                    meta={
                        "doc_id": c.doc_id,
                        "doc_title": c.doc_title,
                        "section_id": c.section_id,
                        "section_title": c.section_title,
                        "citation": c.citation,
                    },
                )
                for c in chunks
            ]
        )
        return cls(store)

    @classmethod
    def from_corpus_dir(cls, corpus_dir: Path | None = None) -> "Retriever":
        return cls.from_chunks(load_corpus(corpus_dir or config.CORPUS_DIR))

    @property
    def size(self) -> int:
        return self._store.count_documents()

    def retrieve(
        self, query: str, *, top_k: int | None = None, doc_ids: list[str] | None = None
    ) -> list[Citation]:
        """Return the top matching passages as citations.

        Args:
            query: the natural-language query.
            top_k: how many to return (defaults to config.TOP_K).
            doc_ids: optional filter to specific documents (e.g. only SR_26-2).
        """
        top_k = top_k or config.TOP_K
        filters = None
        if doc_ids:
            filters = {"field": "meta.doc_id", "operator": "in", "value": doc_ids}
        result = self._bm25.run(query=query, top_k=top_k, filters=filters)
        out: list[Citation] = []
        for doc in result["documents"]:
            meta = doc.meta
            out.append(
                Citation(
                    doc_id=meta["doc_id"],
                    doc_title=meta["doc_title"],
                    section_id=meta["section_id"],
                    section_title=meta["section_title"],
                    text=doc.content or "",
                    score=float(doc.score) if doc.score is not None else 0.0,
                )
            )
        return out
