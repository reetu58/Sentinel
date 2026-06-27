"""Assemble the LangGraph state machine.

    Monitor → (material?) → Investigator → Drafter → [PAUSE] → Human gate → END
                    └────────── not material ──────────────────────────→ END

The graph is compiled with a checkpointer and `interrupt_before=["human_gate"]`,
so execution stops and persists state *before* the gate. Nothing consequential
proceeds until a reviewer's decision is injected and the graph is resumed — the
SR 26-2 human-approval control, enforced structurally rather than by convention.
"""

from __future__ import annotations

from typing import Callable

from langgraph.graph import END, StateGraph

from .audit import AuditSink
from .llm import LLMRouter
from .nodes import make_drafter, make_human_gate, make_investigator, make_monitor
from .state import GraphState


def _route_after_monitor(state: GraphState) -> str:
    return "investigator" if state.get("material") else "stop"


def build_graph(*, sink: AuditSink, retriever, router: LLMRouter, checkpointer):
    """Build and compile the agent graph.

    Args:
        sink: audit sink (Postgres or JSONL).
        retriever: a `rag.Retriever`.
        router: the LLM router.
        checkpointer: a LangGraph checkpointer (e.g. MemorySaver) — required
            for the human-gate interrupt to persist state across the pause.
    """
    g = StateGraph(GraphState)
    g.add_node("monitor", make_monitor(sink))
    g.add_node("investigator", make_investigator(sink, retriever))
    g.add_node("drafter", make_drafter(sink, router))
    g.add_node("human_gate", make_human_gate(sink))

    g.set_entry_point("monitor")
    g.add_conditional_edges(
        "monitor", _route_after_monitor,
        {"investigator": "investigator", "stop": END},
    )
    g.add_edge("investigator", "drafter")
    g.add_edge("drafter", "human_gate")
    g.add_edge("human_gate", END)

    return g.compile(checkpointer=checkpointer, interrupt_before=["human_gate"])
