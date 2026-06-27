"""Immutable audit log for the agent graph.

Every node's input and output, the citations it used, the drafted memo, and the
human decision are recorded append-only. This is the SR 26-2 carve-out control,
so it is core: the graph cannot take a consequential step without a record of
what was decided, on what basis, and (for the gate) by whom.

Two interchangeable sinks behind one interface:
- `PostgresAuditSink` writes to the append-only tables in infra/sql.
- `JsonlAuditSink` appends typed JSON lines to a file. Used for offline
  verification / CI where Postgres isn't running — still genuinely append-only
  (open in append mode; never rewritten).

`open_audit_sink()` returns Postgres when reachable, else JSONL, so the same
graph code records either way.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from . import config


def new_run_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditSink(Protocol):
    backend: str

    def record_agent_run(
        self,
        *,
        run_id: str,
        node: str,
        seq: int,
        model_version: str | None,
        run_date: str | None,
        input: dict[str, Any],
        output: dict[str, Any],
        citations: list[dict[str, Any]],
    ) -> None: ...

    def record_memo(self, *, run_id: str, memo: dict[str, Any]) -> str: ...

    def record_decision(
        self, *, run_id: str, memo_id: str, decision: str, reviewer: str, note: str | None
    ) -> None: ...

    def log(
        self,
        *,
        actor: str,
        action: str,
        target: str,
        citation: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None: ...


# --- JSONL sink (offline) -----------------------------------------------


@dataclass
class JsonlAuditSink:
    """Append-only JSONL audit sink."""

    path: Path
    backend: str = "jsonl"

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, record: dict[str, Any]) -> None:
        record = {"ts": _now(), **record}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str) + "\n")

    def record_agent_run(self, *, run_id, node, seq, model_version, run_date,
                         input, output, citations) -> None:
        self._append(
            {
                "kind": "agent_run",
                "run_id": run_id,
                "node": node,
                "seq": seq,
                "model_version": model_version,
                "run_date": run_date,
                "input": input,
                "output": output,
                "citations": citations,
            }
        )

    def record_memo(self, *, run_id, memo) -> str:
        memo_id = memo.get("id") or str(uuid.uuid4())
        self._append({"kind": "memo", "run_id": run_id, "memo_id": memo_id, "memo": memo})
        return memo_id

    def record_decision(self, *, run_id, memo_id, decision, reviewer, note) -> None:
        self._append(
            {
                "kind": "decision",
                "run_id": run_id,
                "memo_id": memo_id,
                "decision": decision,
                "reviewer": reviewer,
                "note": note,
            }
        )

    def log(self, *, actor, action, target, citation=None, payload=None) -> None:
        self._append(
            {
                "kind": "audit",
                "actor": actor,
                "action": action,
                "target": target,
                "citation": citation,
                "payload": payload or {},
            }
        )


# --- Postgres sink ------------------------------------------------------


@dataclass
class PostgresAuditSink:
    dsn: str
    backend: str = "postgres"

    def _conn(self):
        import psycopg  # lazy

        return psycopg.connect(self.dsn)

    def record_agent_run(self, *, run_id, node, seq, model_version, run_date,
                         input, output, citations) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_runs
                    (run_id, node, seq, model_version, run_date, input, output, citations)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                """,
                (run_id, node, seq, model_version, run_date,
                 json.dumps(input), json.dumps(output), json.dumps(citations)),
            )
            conn.commit()

    def record_memo(self, *, run_id, memo) -> str:
        memo_id = memo.get("id") or str(uuid.uuid4())
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memos
                    (id, run_id, run_date, model_version, metric_label, color,
                     direction, finding, business_implication, policy_basis,
                     recommended_action, citations, full_text, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
                """,
                (
                    memo_id, run_id, memo.get("run_date"), memo.get("model_version"),
                    memo.get("metric_label"), memo.get("color"), memo.get("direction"),
                    memo["finding"], memo["business_implication"], memo["policy_basis"],
                    memo["recommended_action"], json.dumps(memo.get("citations", [])),
                    memo["full_text"], memo.get("status", "pending_approval"),
                ),
            )
            conn.commit()
        return memo_id

    def record_decision(self, *, run_id, memo_id, decision, reviewer, note) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO decisions (memo_id, run_id, decision, reviewer, note)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (memo_id, run_id, decision, reviewer, note),
            )
            conn.commit()

    def log(self, *, actor, action, target, citation=None, payload=None) -> None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (actor, action, target, citation, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (actor, action, target, citation, json.dumps(payload or {})),
            )
            conn.commit()


def open_audit_sink(*, offline: bool = False, dsn: str | None = None) -> AuditSink:
    """Return a Postgres sink when reachable, else the JSONL fallback.

    `offline=True` forces JSONL without attempting a connection.
    """
    if not offline:
        try:
            import psycopg  # noqa: F401

            from pipeline import config as pcfg

            target = dsn or pcfg.POSTGRES_DSN
            sink = PostgresAuditSink(target)
            # Probe the connection so we fail over cleanly if PG isn't up.
            with sink._conn():
                pass
            return sink
        except Exception:
            pass
    return JsonlAuditSink(config.AUDIT_JSONL_PATH)
