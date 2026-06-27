"""RAG tests — chunking, stable citations, and cited retrieval."""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.corpus import load_corpus
from rag.retriever import Retriever

FIXTURES = Path(__file__).parent / "fixtures" / "governance"


def test_corpus_loads_with_canonical_doc_ids():
    chunks = load_corpus(FIXTURES)
    doc_ids = {c.doc_id for c in chunks}
    assert {"SR_26-2", "SR_11-7", "EU_AI_Act", "NIST_AI_RMF", "ModelVal"} <= doc_ids


def test_section_ids_are_stable_and_numbered():
    chunks = load_corpus(FIXTURES)
    sr = {c.section_id: c for c in chunks if c.doc_id == "SR_26-2"}
    # Numbered headings keep their label as the section id.
    assert "III.B" in sr
    assert sr["III.B"].citation == "SR_26-2:III.B"


def test_citations_are_unique_per_doc():
    chunks = load_corpus(FIXTURES)
    cites = [c.citation for c in chunks]
    assert len(cites) == len(set(cites)), "duplicate citations would be ambiguous"


def test_retrieval_returns_citations():
    r = Retriever.from_corpus_dir(FIXTURES)
    assert r.size > 0
    hits = r.retrieve("population stability index near the decision threshold", top_k=3)
    assert hits, "expected at least one hit"
    for h in hits:
        assert h.citation.count(":") == 1
        assert h.doc_id and h.section_id
        assert h.text


def test_retrieval_finds_threshold_guidance():
    r = Retriever.from_corpus_dir(FIXTURES)
    hits = r.retrieve("score distribution shift near decision threshold investigate", top_k=5)
    cites = {h.citation for h in hits}
    # The band-wise/threshold guidance should surface SR 26-2 III.B.
    assert any(c.startswith("SR_26-2") for c in cites)


def test_doc_id_filter():
    r = Retriever.from_corpus_dir(FIXTURES)
    hits = r.retrieve("human oversight intervene", top_k=3, doc_ids=["EU_AI_Act"])
    assert hits
    assert all(h.doc_id == "EU_AI_Act" for h in hits)


def test_missing_corpus_dir_raises():
    with pytest.raises(FileNotFoundError):
        load_corpus(Path("/nonexistent/governance/dir"))
