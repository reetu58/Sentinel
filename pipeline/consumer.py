"""Score the `transactions` stream and publish to `scored-txns`.

Run (after training the model and starting the producer):
    python -m pipeline.consumer
    python -m pipeline.consumer --limit 1000     # stop after N messages

For each raw transaction it:
  1. featurizes via `pipeline.features` (the SAME transform used in training),
  2. scores with the frozen, versioned model,
  3. emits a scored event to `scored-txns` that carries the fraud score, the
     thresholded flag, the model version, AND the ground-truth `isFraud` label.

Carrying the label downstream is deliberate: Phase 2 computes precision/recall/
FPR and fairness slices from this topic, so the truth has to ride along.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from confluent_kafka import Consumer, KafkaError, Producer

from . import config
from .scoring import ModelBundle, load_bundle


def build_consumer(bootstrap: str, group_id: str) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }
    )


def score_event(bundle: ModelBundle, record: dict) -> dict:
    """Build the scored event for one raw transaction record."""
    score = bundle.score_record(record)
    label = record.get(config_label())
    return {
        "txn_id": record.get("txn_id"),
        "fraud_score": round(score, 6),
        "is_fraud_pred": int(score >= bundle.threshold),
        "label": None if label is None else int(label),
        "model_version": bundle.version,
        "type": record.get("type"),
        "amount": record.get("amount"),
        "scored_at": datetime.now(timezone.utc).isoformat(),
    }


def config_label() -> str:
    # Local import avoids a hard module-level dependency cycle in tests.
    from .features import LABEL

    return LABEL


def run(
    *,
    bootstrap: str = config.KAFKA_BOOTSTRAP_SERVERS,
    in_topic: str = config.TRANSACTIONS_TOPIC,
    out_topic: str = config.SCORED_TOPIC,
    model_path: Path = config.MODEL_PATH,
    group_id: str = "sentinel-scorer",
    limit: int | None = None,
) -> int:
    """Consume, score, and publish. Returns the count of scored messages."""
    bundle = load_bundle(model_path)
    print(f"Loaded model version={bundle.version} threshold={bundle.threshold}")

    consumer = build_consumer(bootstrap, group_id)
    consumer.subscribe([in_topic])
    producer = Producer({"bootstrap.servers": bootstrap, "client.id": "sentinel-consumer"})

    scored = 0
    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                raise RuntimeError(msg.error())

            record = json.loads(msg.value().decode("utf-8"))
            event = score_event(bundle, record)
            producer.produce(
                out_topic,
                key=(event["txn_id"] or "").encode("utf-8"),
                value=json.dumps(event).encode("utf-8"),
            )
            producer.poll(0)
            scored += 1

            if scored % 5_000 == 0:
                print(f"  ... scored {scored:,}")
            if limit is not None and scored >= limit:
                break
    finally:
        producer.flush()
        consumer.close()

    print(f"Scored {scored:,} messages -> '{out_topic}'.")
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the transactions stream.")
    parser.add_argument("--bootstrap", default=config.KAFKA_BOOTSTRAP_SERVERS)
    parser.add_argument("--in-topic", default=config.TRANSACTIONS_TOPIC)
    parser.add_argument("--out-topic", default=config.SCORED_TOPIC)
    parser.add_argument("--model", type=Path, default=config.MODEL_PATH)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    run(
        bootstrap=args.bootstrap,
        in_topic=args.in_topic,
        out_topic=args.out_topic,
        model_path=args.model,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
