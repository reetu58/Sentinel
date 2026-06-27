"""CLI to run the Sentinel agent graph on a breach.

Examples:
    # Offline demo on a fixture RED breach (no DB, no API key needed):
    python -m agents.run --breach-file agents/tests/fixtures/breach_red.json \
        --corpus-dir rag/tests/fixtures/governance --offline

    # Approve in the same run (simulating the human gate):
    python -m agents.run --breach-file ... --corpus-dir ... --offline \
        --decision approve --reviewer human:mrm@bank.example

    # Against Postgres (Phase 2 metrics) and the real corpus:
    python -m agents.run --date 2026-06-21 --model-version v1
"""

from __future__ import annotations

import argparse
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from rag.retriever import Retriever

from . import config
from .audit import new_run_id, open_audit_sink
from .graph import build_graph
from .llm import LLMRouter
from .metrics_source import load_from_json, load_from_postgres


def _print_memo(memo: dict) -> None:
    print("\n" + "=" * 78)
    print("DRAFTED ALERT MEMO  (pending human approval)")
    print("=" * 78)
    print(f"\nprovider={memo.get('llm_provider')}  model={memo.get('llm_model')}  "
          f"memo_id={memo.get('id')}")
    print("\n--- (a) Finding ---\n" + memo["finding"])
    print("\n--- (b) Business implication ---\n" + memo["business_implication"])
    print("\n--- (c) Policy basis ---\n" + memo["policy_basis"])
    print("\n--- (d) Recommended action ---\n" + memo["recommended_action"])
    print("\n--- Citations ---")
    for c in memo.get("citations", []):
        print(f"  [{c['citation']}] {c['section_title']}")
    print("\n--- Rendered memo (LLM/offline) ---\n" + memo["full_text"])


def main() -> None:
    p = argparse.ArgumentParser(description="Run the Sentinel agent graph on a breach.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--breach-file", type=Path, help="JSON metrics fixture.")
    src.add_argument("--date", help="run_date (YYYY-MM-DD) to load from Postgres.")
    p.add_argument("--model-version", default="v1")
    p.add_argument("--dsn", default=None)
    p.add_argument("--corpus-dir", type=Path, default=config.REPO_ROOT / "docs" / "governance")
    p.add_argument("--offline", action="store_true", help="Force JSONL audit (no Postgres).")
    p.add_argument("--provider", default=None, help="Override LLM provider.")
    p.add_argument("--decision", choices=["approve", "reject"], default=None,
                   help="If set, supply the human decision and resume through the gate.")
    p.add_argument("--reviewer", default="human:reviewer@example.com")
    p.add_argument("--note", default=None)
    args = p.parse_args()

    retriever = Retriever.from_corpus_dir(args.corpus_dir)
    router = LLMRouter(provider=args.provider)
    sink = open_audit_sink(offline=args.offline, dsn=args.dsn)
    graph = build_graph(sink=sink, retriever=retriever, router=router,
                        checkpointer=MemorySaver())

    if args.breach_file:
        metrics = load_from_json(args.breach_file)
    else:
        from pipeline import config as pcfg
        metrics = load_from_postgres(args.dsn or pcfg.POSTGRES_DSN, args.date, args.model_version)

    run_id = new_run_id()
    run_date = metrics.get("run_date")
    model_version = metrics.get("model_version", args.model_version)
    print(f"run_id={run_id}  audit_backend={sink.backend}  llm={router.provider}")

    cfg = {"configurable": {"thread_id": run_id}}
    state0 = {"run_id": run_id, "run_date": run_date, "model_version": model_version,
              "metrics": metrics, "seq": 0}

    # Runs Monitor -> Investigator -> Drafter, then PAUSES before human_gate.
    result = graph.invoke(state0, cfg)

    if not result.get("material"):
        print("\nMonitor: " + result.get("breach_summary", "no material breach."))
        print("No memo drafted. Done.")
        return

    print("\nMonitor: " + result["breach_summary"])
    print("Objective: " + result["monitor_objective"])
    _print_memo(result["memo"])
    print("\n" + "-" * 78)
    print("GRAPH PAUSED at the human gate. No action taken. Awaiting approve/reject.")

    if args.decision:
        verdict = "approved" if args.decision == "approve" else "rejected"
        graph.update_state(cfg, {"human_decision": {
            "decision": verdict, "reviewer": args.reviewer, "note": args.note}})
        final = graph.invoke(None, cfg)  # resumes INTO human_gate
        print(f"\nHuman decision recorded: {final.get('status', verdict).upper()} "
              f"by {args.reviewer}")
    else:
        print("To record a decision, re-run with --decision approve|reject "
              "(Phase 4 will expose this as an API/dashboard action).")

    if sink.backend == "jsonl":
        print(f"\nAudit log (append-only JSONL): {config.AUDIT_JSONL_PATH}")


if __name__ == "__main__":
    main()
