"""Data access for the API — Postgres (production) or demo (fixtures + JSONL).

Both implement the same `Repository` protocol so the FastAPI routes don't care
which backend is live. Reads only; writes go through the audit sink + the agent
service (which keeps the canonical record append-only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from . import config, demo_data


class Repository(Protocol):
    mode: str

    def get_health(self) -> dict[str, Any]: ...
    def list_investigations(self) -> list[dict[str, Any]]: ...
    def get_investigation(self, run_id: str) -> dict[str, Any] | None: ...
    def upsert_investigation(self, detail: dict[str, Any]) -> None: ...
    def get_audit(self, limit: int = 100) -> list[dict[str, Any]]: ...


# --- Demo repository ----------------------------------------------------


class DemoRepository:
    """Fixtures for health; in-memory registry for investigations; JSONL audit."""

    mode = "demo"

    def __init__(self, audit_path: Path):
        self._audit_path = Path(audit_path)
        self._investigations: dict[str, dict[str, Any]] = {}

    def get_health(self) -> dict[str, Any]:
        return demo_data.load_demo_health()

    def list_investigations(self) -> list[dict[str, Any]]:
        return sorted(
            self._investigations.values(),
            key=lambda d: d.get("created_at") or "",
            reverse=True,
        )

    def get_investigation(self, run_id: str) -> dict[str, Any] | None:
        return self._investigations.get(run_id)

    def upsert_investigation(self, detail: dict[str, Any]) -> None:
        self._investigations[detail["run_id"]] = detail

    def get_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        if not self._audit_path.exists():
            return []
        rows = [json.loads(l) for l in self._audit_path.read_text().splitlines() if l.strip()]
        return list(reversed(rows))[:limit]


# --- Postgres repository ------------------------------------------------


class PostgresRepository:
    """Reads metrics/queue/audit from the Phase 2 + Phase 3 tables."""

    mode = "postgres"

    def __init__(self, dsn: str):
        self._dsn = dsn

    def _conn(self):
        import psycopg

        return psycopg.connect(self._dsn)

    def get_health(self) -> dict[str, Any]:
        from agents.metrics_source import load_from_postgres

        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT run_date, model_version FROM daily_metrics "
                "WHERE metric_kind='psi_score' ORDER BY run_date DESC LIMIT 1"
            )
            row = cur.fetchone()
            if not row:
                raise LookupError("no daily_metrics rows yet")
            run_date, model_version = str(row[0]), row[1]

        metrics = load_from_postgres(self._dsn, run_date, model_version)
        fairness = self._latest_fairness(model_version)
        return {
            "run_date": metrics["run_date"],
            "model_version": metrics["model_version"],
            "psi_score": metrics["score_psi"],
            "feature_csi": metrics.get("feature_csi", []),
            "health": metrics.get("health", {}),
            "trend": metrics.get("trend", {}),
            "fairness": fairness,
        }

    def _latest_fairness(self, model_version: str) -> dict[str, Any]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT run_date, slice_column FROM fairness_metrics "
                "ORDER BY run_date DESC LIMIT 1"
            )
            r = cur.fetchone()
            if not r:
                return {"dataset": "baf", "slice_column": "", "rows": []}
            run_date, slice_column = r
            cur.execute(
                """
                SELECT slice_value, n, fpr, approval_rate, is_reference,
                       payload->>'fpr_gap_vs_overall', payload->>'approval_gap_vs_overall'
                FROM fairness_metrics
                WHERE run_date=%s AND slice_column=%s
                ORDER BY is_reference DESC, slice_value
                """,
                (run_date, slice_column),
            )
            rows = [
                {
                    "slice_value": sv, "n": n, "fpr": float(fpr),
                    "approval_rate": float(ar), "is_reference": bool(ref),
                    "fpr_gap": float(fg or 0.0), "approval_gap": float(ag or 0.0),
                }
                for (sv, n, fpr, ar, ref, fg, ag) in cur.fetchall()
            ]
        return {"dataset": "baf", "slice_column": slice_column, "rows": rows}

    def list_investigations(self) -> list[dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.run_id, m.run_date, m.model_version, m.color, m.direction,
                       m.created_at,
                       COALESCE((SELECT d.decision FROM decisions d
                                 WHERE d.memo_id = m.id
                                 ORDER BY d.ts DESC LIMIT 1), m.status) AS status
                FROM memos m ORDER BY m.created_at DESC
                """
            )
            return [
                {"run_id": str(rid), "run_date": str(rd) if rd else None,
                 "model_version": mv, "color": color, "direction": direction,
                 "created_at": ca.isoformat() if ca else None, "status": status}
                for (rid, rd, mv, color, direction, ca, status) in cur.fetchall()
            ]

    def get_investigation(self, run_id: str) -> dict[str, Any] | None:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, run_date, model_version, color, direction, finding,
                       business_implication, policy_basis, recommended_action,
                       citations, full_text, status, created_at
                FROM memos WHERE run_id=%s ORDER BY created_at DESC LIMIT 1
                """,
                (run_id,),
            )
            m = cur.fetchone()
            if not m:
                return None
            (mid, rd, mv, color, direction, finding, biz, policy, action,
             citations, full_text, status, ca) = m
            cur.execute(
                "SELECT decision FROM decisions WHERE memo_id=%s ORDER BY ts DESC LIMIT 1",
                (mid,),
            )
            d = cur.fetchone()
            status = d[0] if d else status
            cur.execute(
                "SELECT node, seq, jsonb_array_length(citations), ts "
                "FROM agent_runs WHERE run_id=%s ORDER BY seq",
                (run_id,),
            )
            runs = [{"node": n, "seq": s, "n_citations": nc,
                     "ts": ts.isoformat() if ts else None}
                    for (n, s, nc, ts) in cur.fetchall()]
        return {
            "run_id": run_id, "status": status, "created_at": ca.isoformat() if ca else None,
            "agent_runs": runs,
            "memo": {
                "id": str(mid), "color": color, "direction": direction,
                "finding": finding, "business_implication": biz,
                "policy_basis": policy, "recommended_action": action,
                "citations": citations or [], "full_text": full_text,
            },
        }

    def upsert_investigation(self, detail: dict[str, Any]) -> None:
        # No-op: Postgres is the source of truth; the agent service's audit
        # sink already writes memos/decisions. Reads recompute status live.
        return None

    def get_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT ts, actor, action, target, citation, payload "
                "FROM audit_log ORDER BY ts DESC LIMIT %s",
                (limit,),
            )
            return [
                {"kind": "audit", "ts": ts.isoformat() if ts else None,
                 "actor": actor, "action": action, "target": target,
                 "citation": citation, "payload": payload or {}}
                for (ts, actor, action, target, citation, payload) in cur.fetchall()
            ]


def build_repository() -> Repository:
    """Pick the repository per SENTINEL_BACKEND_MODE, falling back to demo."""
    from agents import config as acfg

    mode = config.BACKEND_MODE.lower()
    if mode in ("postgres", "auto"):
        try:
            from pipeline import config as pcfg

            repo = PostgresRepository(pcfg.POSTGRES_DSN)
            with repo._conn():
                pass
            return repo
        except Exception:
            if mode == "postgres":
                raise
    return DemoRepository(acfg.AUDIT_JSONL_PATH)
