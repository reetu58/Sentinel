# Drift & fairness runbook (Phase 2)

How to run the governance metrics layer locally.

## What's in the box

| Component | Where | What it does |
|---|---|---|
| Drift math | `pipeline/drift.py` | PSI / CSI with band-wise per-bin breakdown, bands, direction |
| Health | `pipeline/health.py` | precision / recall / FPR + per-slice fairness gaps |
| Baseline | `pipeline/baseline.py` | frozen reference distribution captured at training time |
| Trend | `pipeline/trend.py` | sustained-rise early warning (before 0.25 breach) |
| Sink | `pipeline/sink_postgres.py` | `scored-txns` topic → `scored_transactions` table |
| Daily job | `pipeline/daily_drift.py` | the runnable Phase 2 entry point |
| Fairness audit | `pipeline/baf_fairness.py` | separate runnable for BAF |
| DAG (Airflow) | `pipeline/dags/daily_drift_dag.py` | thin wrapper over `daily_drift.compute()` |
| Schema | `infra/sql/init.sql` | `scored_transactions`, `model_baselines`, `daily_metrics`, `psi_bins`, `fairness_metrics`, `audit_log` |

## Daily PaySim flow

```bash
# 0. spine is up + PaySim CSV at data/paysim.csv (see data.md)
docker compose -f infra/docker-compose.yml up -d

# 1. train AND freeze the reference baseline alongside the model
python -m pipeline.train_model
#    -> models/fraud_xgb_v1.pkl  +  models/baseline_v1.json

# 2. score the stream (Phase 1 consumer publishes scored-txns)
python -m pipeline.consumer &

# 3. sink scored-txns into Postgres for daily-batch querying
python -m pipeline.sink_postgres &

# 4. replay transactions
python -m pipeline.producer --limit 50000 --rate 1000

# 5. compute one day's metrics
python -m pipeline.daily_drift --date 2026-06-21
```

The CLI is the primary entry point. The Airflow DAG (under
`pipeline/dags/`) is a thin wrapper that calls the same functions — enable it
with `docker compose --profile airflow up -d` and open <http://localhost:8081>.

### Why CLI instead of Airflow as the headline path?

This repo is built solo and verified in environments that may not have Docker
running. The CLI is verifiable end-to-end on a laptop; the DAG is a one-task
shim around `daily_drift.compute()` and `daily_drift.persist()`, so swapping
schedulers (Airflow / cron / Prefect) is a one-import change with no logic to
rewrite. See `infra/docker-compose.yml` for the Airflow service definition.

## BAF fairness audit (separate flow)

```bash
# 0. BAF CSV at data/baf.csv (see data.md)
python -m pipeline.baf_fairness --slice customer_age
python -m pipeline.baf_fairness --slice employment_status --dry-run
```

Writes per-group FPR + approval-rate gaps to the `fairness_metrics` table.

## Querying results

```sql
-- One day's full picture
SELECT metric_kind, metric_name, value, band, color, direction, trend_status
FROM daily_metrics
WHERE run_date = '2026-06-21' AND model_version = 'v1'
ORDER BY metric_kind, value DESC;

-- Band-wise per-bin breakdown for that day's score PSI
SELECT b.bin_index, b.bin_label, b.expected_pct, b.actual_pct,
       b.signed_delta, b.contribution
FROM psi_bins b
JOIN daily_metrics m ON m.id = b.daily_metric_id
WHERE m.run_date = '2026-06-21' AND m.metric_kind = 'psi_score'
ORDER BY b.bin_index;

-- Trend: rolling PSI on the score
SELECT run_date, value, band, color, trend_status, payload->>'slope_per_day'
FROM daily_metrics
WHERE metric_kind = 'trend' AND model_version = 'v1'
ORDER BY run_date DESC LIMIT 14;

-- Fairness gaps for BAF
SELECT slice_value, n, fpr, approval_rate,
       payload->>'fpr_gap_vs_overall' AS fpr_gap
FROM fairness_metrics
WHERE dataset = 'baf' AND slice_column = 'customer_age'
ORDER BY is_reference DESC, slice_value;
```

## Tuning the thresholds

All band edges and trend knobs live in `pipeline/config.py` and are
environment-overridable:

| Env var | Default | Meaning |
|---|---|---|
| `PSI_BAND_MONITOR_MIN` | `0.10` | Lower edge of the AMBER band |
| `PSI_BAND_INVESTIGATE_MIN` | `0.25` | Lower edge of the RED band |
| `TREND_WINDOW_DAYS` | `4` | Days of history for the trend detector |
| `TREND_MIN_TOTAL_DELTA` | `0.03` | Min cumulative rise for the monotone signal |
| `TREND_MIN_SLOPE_PER_DAY` | `0.015` | Min least-squares slope for the slope signal |
