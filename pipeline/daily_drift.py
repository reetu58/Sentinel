"""Daily governance metrics job.

Reads the day's scored transactions from Postgres (sinked off the
`scored-txns` topic by `pipeline.sink_postgres`), computes:

  * PSI on the model SCORE distribution vs the frozen baseline
  * CSI per feature against the same baseline
  * Performance health: precision, recall, FPR, alert volume
  * Trend status — early warning for a sustained PSI creep

…and writes everything (with the band-wise per-bin breakdown) to:

  * `daily_metrics`     — one row per (run_date, model_version, kind, name)
  * `psi_bins`          — band-wise per-bin breakdown for each PSI/CSI row
  * `audit_log`         — one append-only entry attributing the run

Run:
    python -m pipeline.daily_drift --date 2026-06-21
    python -m pipeline.daily_drift --date 2026-06-21 --raw-data data/paysim.csv
    python -m pipeline.daily_drift --date 2026-06-21 --dry-run
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from . import config
from .baseline import BaselineSnapshot, apply_feature_bins, apply_score_bins
from .db import connect
from .drift import PSIResult, csi, direction, edge_labels, psi
from .features import FEATURE_COLUMNS, build_features
from .health import HealthMetrics, metrics
from .scoring import load_bundle
from .trend import TrendFlag, detect

ACTOR = "daily_drift_job"


# --- Data access --------------------------------------------------------


def _load_scored_for_date(
    dsn: str, run_date: date, model_version: str
) -> pd.DataFrame:
    """Pull a day's scored transactions out of Postgres."""
    sql = """
        SELECT txn_id, fraud_score, is_fraud_pred, label, type, amount, scored_at
        FROM scored_transactions
        WHERE scored_at::date = %s AND model_version = %s
    """
    with connect(dsn) as conn:
        return pd.read_sql(sql, conn, params=(run_date, model_version))


def _load_recent_score_psi(
    dsn: str, model_version: str, window: int, before: date
) -> list[tuple[date, float]]:
    """Most-recent N daily score-PSI values for the trend detector."""
    sql = """
        SELECT run_date, value
        FROM daily_metrics
        WHERE model_version = %s
          AND metric_kind = 'psi_score'
          AND run_date < %s
        ORDER BY run_date DESC
        LIMIT %s
    """
    with connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, (model_version, before, window - 1))
        rows = cur.fetchall()
    return list(reversed([(r[0], float(r[1])) for r in rows]))


# --- Compute step (pure, no DB) -----------------------------------------


@dataclass(frozen=True)
class DailyResult:
    run_date: date
    model_version: str
    score_psi: PSIResult
    score_direction: str
    feature_csi: dict[str, PSIResult]
    health: HealthMetrics
    trend: TrendFlag


def compute(
    *,
    run_date: date,
    model_version: str,
    scored: pd.DataFrame,
    raw_for_features: pd.DataFrame,
    baseline: BaselineSnapshot,
    recent_score_psi: Iterable[float],
) -> DailyResult:
    """Run the metric math for one day. Pure: takes data, returns a `DailyResult`.

    Args:
        scored: one row per scored transaction for the day. Must contain
            `fraud_score`, `is_fraud_pred`, `label`.
        raw_for_features: raw rows (same `txn_id` order or aligned) used to
            re-derive feature distributions today. Typically the same source
            CSV passed through `build_features`.
        baseline: frozen reference distribution.
        recent_score_psi: previous-days' score-PSI values, oldest first.
    """
    if scored.empty:
        raise ValueError(f"no scored transactions for {run_date} / {model_version}")

    score_counts_today = apply_score_bins(baseline, scored["fraud_score"].to_numpy())
    score_psi = psi(
        reference_counts=baseline.score.counts_array(),
        current_counts=score_counts_today,
        bin_labels=baseline.score.labels,
    )

    feats_today = build_features(raw_for_features)
    feature_counts_today = apply_feature_bins(baseline, feats_today)
    feature_csi: dict[str, PSIResult] = {}
    for col in FEATURE_COLUMNS:
        ref_dist = baseline.features[col]
        feature_csi[col] = csi(
            reference_counts=ref_dist.counts_array(),
            current_counts=feature_counts_today[col],
            bin_labels=ref_dist.labels,
        )

    health = metrics(
        scored["label"].fillna(0).to_numpy(),
        scored["is_fraud_pred"].to_numpy(),
    )

    trend_series = list(recent_score_psi) + [score_psi.value]
    trend = detect(trend_series)

    return DailyResult(
        run_date=run_date,
        model_version=model_version,
        score_psi=score_psi,
        score_direction=direction(score_psi),
        feature_csi=feature_csi,
        health=health,
        trend=trend,
    )


# --- Persistence --------------------------------------------------------


def persist(dsn: str, result: DailyResult) -> None:
    """Idempotently UPSERT a day's metrics into Postgres."""
    with connect(dsn) as conn, conn.cursor() as cur:
        # Score PSI row
        score_id = _upsert_metric(
            cur,
            run_date=result.run_date,
            model_version=result.model_version,
            metric_kind="psi_score",
            metric_name="psi_score",
            value=result.score_psi.value,
            band=result.score_psi.band,
            color=result.score_psi.color,
            direction=result.score_direction,
            trend_status=None,
            payload={"routing_hint": _routing_hint(result.score_direction)},
        )
        _replace_bins(cur, score_id, result.score_psi)

        # Feature CSI rows
        for feature_name, result_csi in result.feature_csi.items():
            metric_id = _upsert_metric(
                cur,
                run_date=result.run_date,
                model_version=result.model_version,
                metric_kind="csi_feature",
                metric_name=feature_name,
                value=result_csi.value,
                band=result_csi.band,
                color=result_csi.color,
                direction=None,
                trend_status=None,
                payload={},
            )
            _replace_bins(cur, metric_id, result_csi)

        # Health row
        _upsert_metric(
            cur,
            run_date=result.run_date,
            model_version=result.model_version,
            metric_kind="health",
            metric_name="performance",
            value=result.health.precision,  # headline number; full payload below
            band=None,
            color=None,
            direction=None,
            trend_status=None,
            payload=result.health.as_dict(),
        )

        # Trend row
        _upsert_metric(
            cur,
            run_date=result.run_date,
            model_version=result.model_version,
            metric_kind="trend",
            metric_name="score_psi",
            value=result.score_psi.value,
            band=result.score_psi.band,
            color=result.score_psi.color,
            direction=None,
            trend_status=result.trend.status,
            payload=result.trend.as_dict(),
        )

        # Audit log entry
        cur.execute(
            """
            INSERT INTO audit_log (actor, action, target, citation, payload)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                ACTOR,
                "compute_daily_metrics",
                f"daily_metrics:{result.run_date}/{result.model_version}",
                "CLAUDE.md#7-conventions--enforce-throughout",
                json.dumps(_audit_payload(result)),
            ),
        )
        conn.commit()


def _upsert_metric(
    cur,
    *,
    run_date: date,
    model_version: str,
    metric_kind: str,
    metric_name: str,
    value: float | None,
    band: str | None,
    color: str | None,
    direction: str | None,
    trend_status: str | None,
    payload: dict[str, Any],
) -> int:
    cur.execute(
        """
        INSERT INTO daily_metrics
            (run_date, model_version, metric_kind, metric_name,
             value, band, color, direction, trend_status, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (run_date, model_version, metric_kind, metric_name)
        DO UPDATE SET value = EXCLUDED.value,
                      band = EXCLUDED.band,
                      color = EXCLUDED.color,
                      direction = EXCLUDED.direction,
                      trend_status = EXCLUDED.trend_status,
                      payload = EXCLUDED.payload
        RETURNING id
        """,
        (
            run_date,
            model_version,
            metric_kind,
            metric_name,
            value,
            band,
            color,
            direction,
            trend_status,
            json.dumps(payload),
        ),
    )
    return int(cur.fetchone()[0])


def _replace_bins(cur, daily_metric_id: int, result: PSIResult) -> None:
    cur.execute("DELETE FROM psi_bins WHERE daily_metric_id = %s", (daily_metric_id,))
    cur.executemany(
        """
        INSERT INTO psi_bins
            (daily_metric_id, bin_index, bin_label,
             expected_pct, actual_pct, signed_delta, contribution)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        [
            (
                daily_metric_id,
                i,
                b.label,
                b.expected_pct,
                b.actual_pct,
                b.signed_delta,
                b.contribution,
            )
            for i, b in enumerate(result.bins)
        ],
    )


def _routing_hint(score_direction: str) -> dict[str, str]:
    """Map the direction to the Drafter routing table for downstream agents."""
    return {
        "low": "under-detection -> fraud losses + regulatory exposure -> Risk/Finance/Legal",
        "high": "over-flagging -> false declines -> Product/Sales/CX",
        "mid": "threshold instability -> decision instability -> Ops/Finance",
        "stable": "no routing required",
    }.get(score_direction, "unknown")


def _audit_payload(result: DailyResult) -> dict[str, Any]:
    return {
        "score_psi": result.score_psi.value,
        "score_band": result.score_psi.band,
        "score_color": result.score_psi.color,
        "direction": result.score_direction,
        "trend": result.trend.as_dict(),
        "health": result.health.as_dict(),
        "drifting_features": [
            {"feature": name, "csi": r.value, "band": r.band}
            for name, r in result.feature_csi.items()
            if r.band != "stable"
        ],
    }


# --- Verification (no-DB) view ------------------------------------------


def render_summary(result: DailyResult) -> str:
    """Human-readable summary of a `DailyResult`, used by --dry-run."""
    lines: list[str] = []
    sp = result.score_psi
    lines.append(
        f"\n== Daily drift {result.run_date}  model={result.model_version} =="
    )
    lines.append(
        f"\nScore PSI: {sp.value:.4f}  band={sp.band} ({sp.color})  "
        f"direction={result.score_direction}"
    )
    lines.append("  band-wise per-bin breakdown:")
    lines.append("    idx  bin                              expected%  actual%  delta    contrib")
    for i, b in enumerate(sp.bins):
        lines.append(
            f"    {i:>3}  {b.label:<32} {b.expected_pct*100:>8.3f} "
            f"{b.actual_pct*100:>8.3f}  {b.signed_delta*100:>+7.3f}  {b.contribution:>8.4f}"
        )
    drifty = [
        (n, r) for n, r in result.feature_csi.items() if r.band != "stable"
    ]
    if drifty:
        lines.append("\nFeatures with non-stable CSI:")
        for name, r in sorted(drifty, key=lambda kv: -kv[1].value):
            lines.append(f"  {name:<24} csi={r.value:.4f}  {r.band:<11} ({r.color})")
    else:
        lines.append("\nAll feature CSIs in the stable band.")
    h = result.health
    lines.append(
        f"\nHealth: n={h.n}  positives={h.positives}  precision={h.precision:.4f}  "
        f"recall={h.recall:.4f}  fpr={h.fpr:.4f}  f1={h.f1:.4f}"
    )
    lines.append(
        f"\nTrend: {result.trend.status}  signals={list(result.trend.signals)}  "
        f"slope/day={result.trend.slope_per_day:+.4f}  window={result.trend.window_size}"
    )
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute one day's drift + health metrics.")
    parser.add_argument("--date", required=True, help="Run date (YYYY-MM-DD).")
    parser.add_argument("--model", type=Path, default=config.MODEL_PATH)
    parser.add_argument("--baseline", type=Path, default=config.BASELINE_PATH)
    parser.add_argument(
        "--raw-data",
        type=Path,
        default=config.DATA_PATH,
        help="Source CSV used to re-derive per-feature distributions for the day.",
    )
    parser.add_argument("--dsn", default=config.POSTGRES_DSN)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip Postgres writes; print a summary instead.",
    )
    args = parser.parse_args()

    run_date = date.fromisoformat(args.date)
    bundle = load_bundle(args.model)
    baseline = BaselineSnapshot.load(args.baseline)

    if args.dry_run:
        # In dry-run we can't read sinked transactions; require an explicit
        # `--raw-data` and synthesize today's scored frame in-memory by
        # scoring the raw rows through the loaded bundle.
        raw = pd.read_csv(args.raw_data)
        scored = pd.DataFrame(
            {
                "fraud_score": bundle.score_frame(raw),
                "is_fraud_pred": (bundle.score_frame(raw) >= bundle.threshold).astype(int),
                "label": raw.get("isFraud"),
            }
        )
        recent: list[float] = []
        result = compute(
            run_date=run_date,
            model_version=bundle.version,
            scored=scored,
            raw_for_features=raw,
            baseline=baseline,
            recent_score_psi=recent,
        )
        print(render_summary(result))
        return

    scored = _load_scored_for_date(args.dsn, run_date, bundle.version)
    if scored.empty:
        raise SystemExit(
            f"no scored_transactions for {run_date} / {bundle.version}. "
            "Run the sink (pipeline.sink_postgres) first."
        )
    raw = pd.read_csv(args.raw_data)
    recent = [v for _, v in _load_recent_score_psi(
        args.dsn, bundle.version, config.TREND_WINDOW_DAYS, run_date
    )]
    result = compute(
        run_date=run_date,
        model_version=bundle.version,
        scored=scored,
        raw_for_features=raw,
        baseline=baseline,
        recent_score_psi=recent,
    )
    persist(args.dsn, result)
    print(render_summary(result))


if __name__ == "__main__":
    main()
