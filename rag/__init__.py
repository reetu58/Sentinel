"""Sentinel RAG layer — citable retrieval over the governance corpus."""

from .corpus import Chunk, load_corpus
from .retriever import Citation, Retriever

__all__ = ["Chunk", "Citation", "Retriever", "load_corpus"]
