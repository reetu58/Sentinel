"""Shared feature module — the single source of truth for train AND serve.

CLAUDE.md convention (non-negotiable): train and serve features must be
identical. `train_model.py` and `consumer.py` (via `scoring.py`) both import
`build_features` from here. There is no parallel implementation, and there must
never be one. Train/serve skew is exactly the failure Sentinel exists to catch,
so the model that does the catching must not commit it itself.

To keep parity exact, every transform is **stateless and frozen**:

- The set and order of output columns is fixed (`FEATURE_COLUMNS`).
- The transaction `type` is one-hot encoded against a frozen vocabulary, so an
  unseen type deterministically yields all-zero type columns rather than a new
  column. No encoder is fit at runtime.
- Missing / non-numeric balances fill to 0.0.

The same single record scored in the streaming consumer therefore produces
byte-identical features to that record seen during training.

PaySim raw schema (mobile-money simulator, fully labeled):
    step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig,
    nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

#: Label column (1 = fraud) in PaySim.
LABEL: str = "isFraud"

#: Frozen vocabulary of transaction types. PaySim fraud occurs only in
#: TRANSFER and CASH_OUT, but all five are encoded so the schema is stable.
TYPE_VOCAB: tuple[str, ...] = ("CASH_IN", "CASH_OUT", "DEBIT", "PAYMENT", "TRANSFER")

#: Raw numeric balance/amount columns carried through.
_RAW_NUMERIC: tuple[str, ...] = (
    "amount",
    "oldbalanceOrg",
    "newbalanceOrig",
    "oldbalanceDest",
    "newbalanceDest",
)

#: Engineered numerics. The "error balance" terms are the classic strong PaySim
#: signals: for a clean transaction the balances reconcile against the amount,
#: so a non-zero residual is highly informative.
_ENGINEERED_NUMERIC: tuple[str, ...] = ("errorBalanceOrig", "errorBalanceDest")

#: The fixed, ordered output schema. Training and scoring both rely on this.
FEATURE_COLUMNS: tuple[str, ...] = (
    *_RAW_NUMERIC,
    *_ENGINEERED_NUMERIC,
    *(f"type_{t}" for t in TYPE_VOCAB),
)


def _coerce_numeric(frame: pd.DataFrame, col: str) -> pd.Series:
    if col in frame.columns:
        return pd.to_numeric(frame[col], errors="coerce").fillna(0.0)
    return pd.Series(0.0, index=frame.index)


def build_features(raw: pd.DataFrame) -> pd.DataFrame:
    """Transform raw PaySim rows into the model feature matrix.

    Pure and stateless: identical input always yields identical output, whether
    called on a full training frame or a single-row frame at serve time.

    Args:
        raw: DataFrame with PaySim raw columns. Missing columns are treated as
             all-zero / out-of-vocabulary so partial records still score
             deterministically.

    Returns:
        DataFrame of float features with columns exactly `FEATURE_COLUMNS`, in
        that order, indexed like `raw`.
    """
    amount = _coerce_numeric(raw, "amount")
    old_org = _coerce_numeric(raw, "oldbalanceOrg")
    new_org = _coerce_numeric(raw, "newbalanceOrig")
    old_dest = _coerce_numeric(raw, "oldbalanceDest")
    new_dest = _coerce_numeric(raw, "newbalanceDest")

    out = pd.DataFrame(index=raw.index)
    out["amount"] = amount
    out["oldbalanceOrg"] = old_org
    out["newbalanceOrig"] = new_org
    out["oldbalanceDest"] = old_dest
    out["newbalanceDest"] = new_dest

    # Residual between expected and observed post-transaction balances.
    out["errorBalanceOrig"] = new_org + amount - old_org
    out["errorBalanceDest"] = old_dest + amount - new_dest

    # One-hot the transaction type against the frozen vocabulary.
    type_series = (
        raw["type"].astype("string")
        if "type" in raw.columns
        else pd.Series(pd.NA, index=raw.index, dtype="string")
    )
    for t in TYPE_VOCAB:
        out[f"type_{t}"] = (type_series == t).astype("float64")

    return out[list(FEATURE_COLUMNS)].astype("float64")


def build_features_one(record: Mapping[str, Any]) -> pd.DataFrame:
    """Featurize a single raw transaction record (e.g. a Kafka message value).

    Thin convenience wrapper over `build_features` so the serving path uses the
    exact same transform as training — never a hand-rolled per-field copy.
    """
    return build_features(pd.DataFrame([dict(record)]))
