"""Shared runtime configuration, read from the environment.

One place for Kafka/topic/model wiring AND the governance thresholds (PSI
bands, trend-detector windows). Values come from `.env` locally (see
`.env.example`); no secrets live here.
"""

from __future__ import annotations

import os
from pathlib import Path

# --- Kafka / topics ------------------------------------------------------

#: Kafka / Redpanda bootstrap servers (Redpanda speaks the Kafka protocol).
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

#: Topic carrying raw replayed transactions.
TRANSACTIONS_TOPIC: str = os.getenv("KAFKA_TRANSACTIONS_TOPIC", "transactions")

#: Topic carrying scored transactions (score + label) for downstream metrics.
SCORED_TOPIC: str = os.getenv("KAFKA_SCORED_TXNS_TOPIC", "scored-txns")

# --- Paths ----------------------------------------------------------------

#: Repo paths. `data/` and `models/` are gitignored — never committed.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_PATH: Path = Path(os.getenv("PAYSIM_CSV", REPO_ROOT / "data" / "paysim.csv"))
MODEL_PATH: Path = Path(os.getenv("MODEL_PATH", REPO_ROOT / "models" / "fraud_xgb_v1.pkl"))

#: Frozen reference baseline produced at training time; lives next to the model.
BASELINE_PATH: Path = Path(
    os.getenv("BASELINE_PATH", REPO_ROOT / "models" / "baseline_v1.json")
)

#: Bank Account Fraud Suite CSV (Phase 2 fairness audit). Public data, never
#: committed. The fairness module gates on this file existing.
BAF_CSV: Path = Path(os.getenv("BAF_CSV", REPO_ROOT / "data" / "baf.csv"))

# --- Scoring --------------------------------------------------------------

#: Decision threshold for the fraud flag. Matches the training report cut.
DECISION_THRESHOLD: float = float(os.getenv("DECISION_THRESHOLD", "0.85"))

# --- Governance thresholds -----------------------------------------------

#: PSI/CSI band edges, per CLAUDE.md:
#:   < PSI_BAND_MONITOR_MIN       -> stable      / GREEN
#:   < PSI_BAND_INVESTIGATE_MIN   -> monitor     / AMBER
#:   else                         -> investigate / RED
PSI_BAND_MONITOR_MIN: float = float(os.getenv("PSI_BAND_MONITOR_MIN", "0.10"))
PSI_BAND_INVESTIGATE_MIN: float = float(os.getenv("PSI_BAND_INVESTIGATE_MIN", "0.25"))

#: Trend detector: how many most-recent daily readings to consider.
TREND_WINDOW_DAYS: int = int(os.getenv("TREND_WINDOW_DAYS", "4"))

#: Trend detector: monotone-rise signal requires total delta over the window
#: to exceed this (catches "0.04 -> 0.05 -> 0.07 -> 0.08" style creeps).
TREND_MIN_TOTAL_DELTA: float = float(os.getenv("TREND_MIN_TOTAL_DELTA", "0.03"))

#: Trend detector: positive-slope signal requires least-squares slope per day
#: to exceed this. Set conservatively so noise doesn't fire it.
TREND_MIN_SLOPE_PER_DAY: float = float(os.getenv("TREND_MIN_SLOPE_PER_DAY", "0.015"))

# --- Postgres -------------------------------------------------------------

#: DSN for the metrics + audit log database. Defaults match docker-compose.
POSTGRES_DSN: str = os.getenv(
    "POSTGRES_DSN",
    "postgresql://sentinel:sentinel@localhost:5432/sentinel",
)
