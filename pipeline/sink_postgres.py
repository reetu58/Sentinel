"""Sink scored events from the `scored-txns` Kafka topic into Postgres.

The daily drift job needs a queryable history of scored transactions; Kafka
retention isn't the right place to look up "all of yesterday's scores". This
sink consumes `scored-txns` and inserts each event into the
`scored_transactions` table, idempotently on (txn_id, model_version).

Run (typically as a long-lived process next to the consumer):

    python -m pipeline.sink_postgres
    python -m pipeline.sink_postgres --limit 5000      # quick test
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime

from confluent_kafka import Consumer, KafkaError

from . import config
from .db import connect


_INSERT_SQL = """
INSERT INTO scored_transactions
    (txn_id, fraud_score, is_fraud_pred, label, model_version, type, amount, scored_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (txn_id, model_version) DO NOTHING;
"""


def _row_from_event(event: dict) -> tuple:
    scored_at = event.get("scored_at")
    ts = datetime.fromisoformat(scored_at) if scored_at else datetime.utcnow()
    return (
        event.get("txn_id"),
        float(event["fraud_score"]),
        int(event["is_fraud_pred"]),
        None if event.get("label") is None else int(event["label"]),
        str(event["model_version"]),
        event.get("type"),
        None if event.get("amount") is None else float(event["amount"]),
        ts,
    )


def run(
    *,
    bootstrap: str = config.KAFKA_BOOTSTRAP_SERVERS,
    in_topic: str = config.SCORED_TOPIC,
    dsn: str = config.POSTGRES_DSN,
    group_id: str = "sentinel-pg-sink",
    limit: int | None = None,
    batch_size: int = 500,
) -> int:
    """Consume from `in_topic` and upsert each event into Postgres."""
    consumer = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )
    consumer.subscribe([in_topic])

    written = 0
    buffer: list[tuple] = []
    try:
        with connect(dsn) as conn, conn.cursor() as cur:
            while True:
                msg = consumer.poll(1.0)
                if msg is None:
                    if buffer:
                        cur.executemany(_INSERT_SQL, buffer)
                        conn.commit()
                        written += len(buffer)
                        buffer.clear()
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise RuntimeError(msg.error())

                event = json.loads(msg.value().decode("utf-8"))
                buffer.append(_row_from_event(event))

                if len(buffer) >= batch_size:
                    cur.executemany(_INSERT_SQL, buffer)
                    conn.commit()
                    written += len(buffer)
                    buffer.clear()
                    if written % 5_000 == 0:
                        print(f"  ... sinked {written:,}")

                if limit is not None and written + len(buffer) >= limit:
                    if buffer:
                        cur.executemany(_INSERT_SQL, buffer)
                        conn.commit()
                        written += len(buffer)
                        buffer.clear()
                    break
    finally:
        consumer.close()

    print(f"Sinked {written:,} events into scored_transactions.")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Sink scored-txns into Postgres.")
    parser.add_argument("--bootstrap", default=config.KAFKA_BOOTSTRAP_SERVERS)
    parser.add_argument("--in-topic", default=config.SCORED_TOPIC)
    parser.add_argument("--dsn", default=config.POSTGRES_DSN)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run(bootstrap=args.bootstrap, in_topic=args.in_topic, dsn=args.dsn, limit=args.limit)


if __name__ == "__main__":
    main()
