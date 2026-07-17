"""LangGraph state for the Sentinel agent graph.

A single dict threaded through Monitor -> Investigator -> Drafter -> Human gate.
Kept as a TypedDict (total=False) so each node contributes its slice.
"""

from __future__ import annotations

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    # Identity / provenance
    run_id: str
    run_date: str
    model_version: str
    seq: int  # monotonically increasing agent_runs sequence within the run

    # Input metrics (loaded from Postgres or a fixture)
    metrics: dict[str, Any]

    # Monitor output
    material: bool
    breach_summary: str
    monitor_objective: str

    # Investigator output
    direction: str
    mechanism: str
    threshold_note: str
    citations: list[dict[str, Any]]

    # Drafter output
    memo: dict[str, Any]

    # Human gate
    human_decision: dict[str, Any]  # {"decision","reviewer","note"} injected on resume
    status: str  # 'pending_approval' | 'approved' | 'rejected' | 'no_action'
