"""Agent-graph tests — router, materiality, direction, gate pause, citations.

All offline (deterministic composer + JSONL audit), so they run in CI without
API keys or a database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from agents.audit import JsonlAuditSink, new_run_id
from agents.graph import build_graph
from agents.llm import LLMRouter, resolve_provider
from rag.retriever import Retriever

FIXTURES = Path(__file__).parent / "fixtures"
GOV = Path(__file__).resolve().parents[2] / "rag" / "tests" / "fixtures" / "governance"


@pytest.fixture
def retriever():
    return Retriever.from_corpus_dir(GOV)


@pytest.fixture
def sink(tmp_path):
    return JsonlAuditSink(tmp_path / "audit.jsonl")


def _breach(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_router_resolves_offline_without_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "auto")
    assert resolve_provider() == "offline"


def test_offline_router_renders_four_part_memo():
    router = LLMRouter(provider="offline")
    facts = {
        "metric_label": "score PSI", "psi_value": 0.47, "band": "investigate",
        "color": "RED", "direction": "high", "mechanism": "the model is over-flagging",
        "cost_type": "false declines", "route_to": "Product / Sales / CX",
        "recommended_action": "Review the threshold.",
        "citations": [{"citation": "SR_26-2:III.B", "section_title": "Thresholds"}],
    }
    resp = router.complete("system", f"<facts>{json.dumps(facts)}</facts>")
    assert "(a) Finding" in resp.text
    assert "(b) Business implication" in resp.text
    assert "(c) Policy basis" in resp.text
    assert "(d) Recommended action" in resp.text
    assert "SR_26-2:III.B" in resp.text


def test_red_breach_produces_cited_memo_and_pauses(retriever, sink):
    graph = build_graph(sink=sink, retriever=retriever, router=LLMRouter("offline"),
                        checkpointer=MemorySaver())
    rid = new_run_id()
    cfg = {"configurable": {"thread_id": rid}}
    metrics = _breach("breach_red.json")
    result = graph.invoke(
        {"run_id": rid, "run_date": metrics["run_date"],
         "model_version": metrics["model_version"], "metrics": metrics, "seq": 0},
        cfg,
    )
    assert result["material"] is True
    memo = result["memo"]
    assert memo["direction"] == "high"
    assert "Product / Sales / CX" in memo["business_implication"]
    assert memo["citations"], "memo must carry citations"
    # Paused before the gate: status still pending, no decision recorded.
    assert result.get("status") == "pending_approval"
    snap = graph.get_state(cfg)
    assert snap.next == ("human_gate",), "graph must be paused before human_gate"


def test_human_gate_records_decision_on_resume(retriever, sink):
    graph = build_graph(sink=sink, retriever=retriever, router=LLMRouter("offline"),
                        checkpointer=MemorySaver())
    rid = new_run_id()
    cfg = {"configurable": {"thread_id": rid}}
    metrics = _breach("breach_red.json")
    graph.invoke(
        {"run_id": rid, "run_date": metrics["run_date"],
         "model_version": metrics["model_version"], "metrics": metrics, "seq": 0},
        cfg,
    )
    graph.update_state(cfg, {"human_decision": {
        "decision": "approved", "reviewer": "human:test", "note": None}})
    final = graph.invoke(None, cfg)
    assert final["status"] == "approved"

    # Audit log has a decision row from a human actor.
    rows = [json.loads(l) for l in sink.path.read_text().splitlines()]
    assert any(r["kind"] == "decision" and r["decision"] == "approved" for r in rows)
    assert any(r["kind"] == "audit" and r["actor"] == "human:test" for r in rows)


def test_non_material_breach_stops_without_memo(retriever, sink, tmp_path):
    # A GREEN, flat breach should not escalate.
    metrics = {
        "run_date": "2026-06-22", "model_version": "v1",
        "score_psi": {"value": 0.03, "band": "stable", "color": "GREEN",
                      "direction": "stable", "bins": [
                          {"label": "b", "expected_pct": 0.5, "actual_pct": 0.5,
                           "signed_delta": 0.0, "contribution": 0.0}]},
        "feature_csi": [], "health": {"n": 1000, "fpr": 0.01},
        "trend": {"status": "flat"},
    }
    graph = build_graph(sink=sink, retriever=retriever, router=LLMRouter("offline"),
                        checkpointer=MemorySaver())
    rid = new_run_id()
    cfg = {"configurable": {"thread_id": rid}}
    result = graph.invoke(
        {"run_id": rid, "run_date": "2026-06-22", "model_version": "v1",
         "metrics": metrics, "seq": 0}, cfg)
    assert result["material"] is False
    assert "memo" not in result
    snap = graph.get_state(cfg)
    assert snap.next == (), "non-material run should reach END, not the gate"
