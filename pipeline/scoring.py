"""Load the frozen model and score transactions — the shared serving path.

`consumer.py` uses this so the scoring logic is importable and testable without
a running Kafka broker. The model bundle is whatever `train_model.py` froze: the
fitted estimator plus the feature schema and metadata it was trained against.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .features import FEATURE_COLUMNS, build_features, build_features_one


@dataclass(frozen=True)
class ModelBundle:
    """A frozen, versioned model plus the schema it was trained against."""

    model: Any
    feature_columns: tuple[str, ...]
    threshold: float
    version: str
    metadata: dict[str, Any]

    def _check_schema(self) -> None:
        if tuple(self.feature_columns) != tuple(FEATURE_COLUMNS):
            raise ValueError(
                "feature schema drift: the loaded model was trained on a "
                "different feature set than pipeline.features defines. Retrain "
                "before serving."
            )

    def score_frame(self, raw: pd.DataFrame) -> pd.Series:
        """Probability of fraud for each raw row."""
        self._check_schema()
        feats = build_features(raw)[list(self.feature_columns)]
        proba = self.model.predict_proba(feats)[:, 1]
        return pd.Series(proba, index=raw.index, name="fraud_score")

    def score_record(self, record: Mapping[str, Any]) -> float:
        """Probability of fraud for a single raw record."""
        self._check_schema()
        feats = build_features_one(record)[list(self.feature_columns)]
        return float(self.model.predict_proba(feats)[0, 1])


def load_bundle(path: str | Path) -> ModelBundle:
    """Load a frozen model bundle from a pickle written by `train_model.py`."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"model not found at {path}. Train it first: "
            "python -m pipeline.train_model"
        )
    with path.open("rb") as fh:
        obj = pickle.load(fh)
    return ModelBundle(
        model=obj["model"],
        feature_columns=tuple(obj["feature_columns"]),
        threshold=float(obj["threshold"]),
        version=str(obj["version"]),
        metadata=dict(obj.get("metadata", {})),
    )
