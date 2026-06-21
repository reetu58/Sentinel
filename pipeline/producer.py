"""Replay PaySim rows into the `transactions` Kafka topic.

Run:
    python -m pipeline.producer                 # full file, ~50 msg/s
    python -m pipeline.producer --limit 1000    # quick test
    python -m pipeline.producer --rate 200      # 200 msg/s

Each row gets a stable `txn_id` (its 0-based row index, zero-padded) so the same
transaction always carries the same id across replays — the consumer and the
audit log can join on it. The message value is the raw transaction as JSON,
including `isFraud`, so the scored stream can carry the ground-truth label
through for Phase 2 precision/recall/FPR.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd
from confluent_kafka import Producer

from . import config


def make_txn_id(row_index: int) -> str:
    """Stable, sortable id for a PaySim row (no native id in the dataset)."""
    return f"paysim-{row_index:09d}"


def build_producer(bootstrap: str) -> Producer:
    return Producer(
        {
            "bootstrap.servers": bootstrap,
            "linger.ms": 50,
            "client.id": "sentinel-producer",
        }
    )


def replay(
    csv_path: Path,
    *,
    bootstrap: str = config.KAFKA_BOOTSTRAP_SERVERS,
    topic: str = config.TRANSACTIONS_TOPIC,
    rate: float = 50.0,
    limit: int | None = None,
) -> int:
    """Stream rows from `csv_path` to `topic`. Returns the count produced."""
    if not csv_path.exists():
        raise FileNotFoundError(
            f"PaySim CSV not found at {csv_path}. See docs/runbooks/data.md."
        )

    producer = build_producer(bootstrap)
    interval = 1.0 / rate if rate > 0 else 0.0
    sent = 0

    # Chunked read so a multi-GB PaySim file never has to fit in memory at once.
    reader = pd.read_csv(csv_path, chunksize=10_000)
    row_index = 0
    for chunk in reader:
        for record in chunk.to_dict(orient="records"):
            if limit is not None and sent >= limit:
                producer.flush()
                print(f"Produced {sent} messages to '{topic}' (limit reached).")
                return sent

            txn_id = make_txn_id(row_index)
            record["txn_id"] = txn_id
            producer.produce(
                topic,
                key=txn_id.encode("utf-8"),
                value=json.dumps(record, default=str).encode("utf-8"),
            )
            producer.poll(0)  # serve delivery callbacks without blocking
            sent += 1
            row_index += 1

            if sent % 5_000 == 0:
                print(f"  ... produced {sent:,}")
            if interval:
                time.sleep(interval)

    producer.flush()
    print(f"Produced {sent:,} messages to '{topic}'.")
    return sent


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay PaySim into Kafka.")
    parser.add_argument("--data", type=Path, default=config.DATA_PATH)
    parser.add_argument("--bootstrap", default=config.KAFKA_BOOTSTRAP_SERVERS)
    parser.add_argument("--topic", default=config.TRANSACTIONS_TOPIC)
    parser.add_argument("--rate", type=float, default=50.0, help="messages/sec (0 = unthrottled)")
    parser.add_argument("--limit", type=int, default=None, help="stop after N messages")
    args = parser.parse_args()

    replay(
        args.data,
        bootstrap=args.bootstrap,
        topic=args.topic,
        rate=args.rate,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
