"""Agent-graph orchestration for the API.

Holds one compiled LangGraph graph backed by a **SQLite checkpointer**, so the
graph paused before the human gate survives between the (separate) trigger and
approve/reject HTTP requests — and across process restarts. All state is
server-side; the client only sends a run_id and a decision.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite import SqliteSaver

from agents.audit import AuditSink, new_run_id
from agents.graph import build_graph
from agents.llm import LLMRouter
from rag.retriever import Retriever

from .repository import Repository


class HumanGateError(RuntimeError):
    """Raised when a decision is requested on a run that isn't awaiting one."""


class AgentService:
    def __init__(
        self,
        *,
        repo: Repository,
        sink: AuditSink,
        retriever: Retriever,
        router: LLMRouter,
        checkpoint_db: Path,
    ):
        self.repo = repo
        self.sink = sink
        self.router = router
        checkpoint_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(checkpoint_db), check_same_thread=False)
        self._saver = SqliteSaver(conn)
        self.graph = build_graph(
            sink=sink, retriever=retriever, router=router, checkpointer=self._saver
        )

    # --- trigger ---------------------------------------------------------

    def trigger(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Run Monitor → Investigator → Drafter; pause before the human gate."""
        run_id = new_run_id()
        run_date = metrics.get("run_date")
        model_version = metrics.get("model_version")
        cfg = {"configurable": {"thread_id": run_id}}
        state0 = {
            "run_id": run_id, "run_date": run_date,
            "model_version": model_version, "metrics": metrics, "seq": 0,
        }
        result = self.graph.invoke(state0, cfg)
        detail = self._detail_from_state(run_id, result)
        self.repo.upsert_investigation(detail)
        return detail

    # --- decide ----------------------------------------------------------

    def decide(self, run_id: str, decision: str, reviewer: str, note: str | None) -> dict[str, Any]:
        """Resume the paused graph with a human decision (approve|reject)."""
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be 'approve' or 'reject'")
        cfg = {"configurable": {"thread_id": run_id}}
        snapshot = self.graph.get_state(cfg)
        if not snapshot or not snapshot.values:
            raise HumanGateError(f"unknown run_id {run_id}")
        if snapshot.next != ("human_gate",):
            raise HumanGateError(
                f"run {run_id} is not awaiting approval (already decided?)"
            )

        verdict = "approved" if decision == "approve" else "rejected"
        self.graph.update_state(
            cfg,
            {"human_decision": {"decision": verdict, "reviewer": reviewer, "note": note}},
        )
        final = self.graph.invoke(None, cfg)  # resumes INTO human_gate

        detail = self.repo.get_investigation(run_id) or self._detail_from_state(run_id, final)
        detail["status"] = final.get("status", verdict)
        self.repo.upsert_investigation(detail)
        return detail

    # --- helpers ---------------------------------------------------------

    def _detail_from_state(self, run_id: str, state: dict[str, Any]) -> dict[str, Any]:
        material = state.get("material", False)
        memo = state.get("memo")
        status = state.get("status") or ("pending_approval" if material else "no_action")
        agent_runs = self._agent_runs_from_state(state)
        return {
            "run_id": run_id,
            "status": status,
            "breach_summary": state.get("breach_summary"),
            "objective": state.get("monitor_objective"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "memo": memo,
            "agent_runs": agent_runs,
        }

    @staticmethod
    def _agent_runs_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
        runs: list[dict[str, Any]] = []
        if state.get("breach_summary"):
            runs.append({"node": "monitor", "seq": 1, "n_citations": 0})
        if state.get("citations") is not None:
            runs.append({"node": "investigator", "seq": 2,
                         "n_citations": len(state.get("citations", []))})
        if state.get("memo"):
            runs.append({"node": "drafter", "seq": 3,
                         "n_citations": len(state.get("citations", []))})
        return runs
