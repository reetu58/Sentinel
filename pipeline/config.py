"""Shared runtime configuration, read from the environment.

Keeps Kafka/topic/model wiring in one place so the producer, consumer, and
training script agree. Values come from `.env` locally (see `.env.example`);
no secrets live here.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Kafka / Redpanda bootstrap servers (Redpanda speaks the Kafka protocol).
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

#: Topic carrying raw replayed transactions.
TRANSACTIONS_TOPIC: str = os.getenv("KAFKA_TRANSACTIONS_TOPIC", "transactions")

#: Topic carrying scored transactions (score + label) for downstream metrics.
SCORED_TOPIC: str = os.getenv("KAFKA_SCORED_TXNS_TOPIC", "scored-txns")

#: Repo paths. `data/` and `models/` are gitignored — never committed.
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_PATH: Path = Path(os.getenv("PAYSIM_CSV", REPO_ROOT / "data" / "paysim.csv"))
MODEL_PATH: Path = Path(os.getenv("MODEL_PATH", REPO_ROOT / "models" / "fraud_xgb_v1.pkl"))

#: Decision threshold for the fraud flag. Matches the training report cut.
DECISION_THRESHOLD: float = float(os.getenv("DECISION_THRESHOLD", "0.85"))
