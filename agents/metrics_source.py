"""Load the day's metrics for the Monitor — from Postgres or a JSON fixture.

The graph operates on a plain metrics dict so it's testable without a database.
Postgres is the production source (written by Phase 2's daily_drift); the JSON
loader feeds fixtures for offline verification / CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_from_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_from_postgres(dsn: str, run_date: str, model_version: str) -> dict[str, Any]:
    """Reconstruct the metrics dict from the Phase 2 tables."""
    import psycopg

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        # Score PSI row + its id (for the band-wise bins).
        cur.execute(
            """
            SELECT id, value, band, color, direction
            FROM daily_metrics
            WHERE run_date=%s AND model_version=%s AND metric_kind='psi_score'
            """,
            (run_date, model_version),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"no psi_score metric for {run_date}/{model_version}")
        score_id, value, band, color, direction = row

        cur.execute(
            """
            SELECT bin_label, expected_pct, actual_pct, signed_delta, contribution
            FROM psi_bins WHERE daily_metric_id=%s ORDER BY bin_index
            """,
            (score_id,),
        )
        bins = [
            {"label": l, "expected_pct": e, "actual_pct": a,
             "signed_delta": d, "contribution": c}
            for (l, e, a, d, c) in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT metric_name, value, band
            FROM daily_metrics
            WHERE run_date=%s AND model_version=%s AND metric_kind='csi_feature'
            ORDER BY value DESC
            """,
            (run_date, model_version),
        )
        feature_csi = [{"feature": n, "value": v, "band": b} for (n, v, b) in cur.fetchall()]

        cur.execute(
            """
            SELECT payload FROM daily_metrics
            WHERE run_date=%s AND model_version=%s AND metric_kind='health'
            """,
            (run_date, model_version),
        )
        h = cur.fetchone()
        health = h[0] if h else {}

        cur.execute(
            """
            SELECT trend_status, payload FROM daily_metrics
            WHERE run_date=%s AND model_version=%s AND metric_kind='trend'
            """,
            (run_date, model_version),
        )
        t = cur.fetchone()
        trend = {"status": t[0], **(t[1] or {})} if t else {"status": "flat"}

    return {
        "run_date": run_date,
        "model_version": model_version,
        "score_psi": {
            "value": float(value), "band": band, "color": color,
            "direction": direction, "bins": bins,
        },
        "feature_csi": feature_csi,
        "health": health,
        "trend": trend,
    }
