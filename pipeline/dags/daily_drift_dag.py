"""Airflow DAG that wraps `pipeline.daily_drift`.

A deliberately thin shim: all computation lives in `daily_drift.compute()` and
`daily_drift.persist()`, both of which are runnable standalone via the CLI.
This DAG just schedules them, so swapping schedulers (Airflow / cron / Prefect)
is a one-import change with no logic to rewrite.

Phase 2 ships the CLI as the primary entry point — it's verifiable without a
running scheduler. This DAG is mounted into the Airflow container by the
service in `infra/docker-compose.yml`; it parses cleanly without any external
state, but obviously needs a populated Postgres + frozen baseline to actually
run a task.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

# The Airflow import is intentionally lazy/conditional so this file is safe to
# import outside an Airflow environment (e.g. for `pytest --collect-only`).
try:
    from airflow.decorators import dag, task  # type: ignore
except ImportError:  # pragma: no cover -- only happens in non-Airflow envs
    dag = None  # type: ignore
    task = None  # type: ignore


def _build_dag():
    from pipeline import config  # local import for Airflow worker
    from pipeline.daily_drift import (
        _load_recent_score_psi,
        _load_scored_for_date,
        compute,
        persist,
    )
    from pipeline.baseline import BaselineSnapshot
    from pipeline.scoring import load_bundle
    import pandas as pd

    @dag(
        dag_id="sentinel_daily_drift",
        description="Daily PSI / CSI / health metrics + trend detection.",
        start_date=datetime(2026, 1, 1),
        schedule="@daily",
        catchup=False,
        default_args={
            "owner": "sentinel",
            "retries": 1,
            "retry_delay": timedelta(minutes=5),
        },
        tags=["sentinel", "phase-2", "governance"],
    )
    def daily_drift():
        @task
        def run(ds: str | None = None) -> str:
            run_date = date.fromisoformat(ds) if ds else date.today()
            bundle = load_bundle(config.MODEL_PATH)
            baseline = BaselineSnapshot.load(config.BASELINE_PATH)
            scored = _load_scored_for_date(
                config.POSTGRES_DSN, run_date, bundle.version
            )
            if scored.empty:
                raise RuntimeError(
                    f"no scored_transactions for {run_date} / {bundle.version}"
                )
            raw = pd.read_csv(config.DATA_PATH)
            recent = [
                v for _, v in _load_recent_score_psi(
                    config.POSTGRES_DSN,
                    bundle.version,
                    config.TREND_WINDOW_DAYS,
                    run_date,
                )
            ]
            result = compute(
                run_date=run_date,
                model_version=bundle.version,
                scored=scored,
                raw_for_features=raw,
                baseline=baseline,
                recent_score_psi=recent,
            )
            persist(config.POSTGRES_DSN, result)
            return f"{run_date} / {bundle.version}"

        run()

    return daily_drift()


# When parsed inside Airflow, expose the DAG at module level.
if dag is not None:  # pragma: no cover -- Airflow-only path
    daily_drift_dag = _build_dag()
