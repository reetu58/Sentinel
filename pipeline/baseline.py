"""Frozen reference baseline — what daily drift jobs compare against.

Captured once, at training time, from the same training frame the model saw.
Stored alongside the model bundle and versioned with it: a PSI of 0.18 only
means something when read against a specific (model_version, baseline_version)
pair, so every daily metric row carries both.

The baseline holds bin edges + reference counts for:
  - the model SCORE distribution (used for PSI on the score)
  - each model feature (used for CSI per feature)

Numeric features get quantile-decile bins; the `type_*` one-hot features
(binary by construction) get fixed two-bin edges. The whole snapshot is JSON
so it's diff-able, sidecar-friendly, and easy to load into Postgres jsonb.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .drift import bin_counts, edge_labels, quantile_bin_edges
from .features import FEATURE_COLUMNS, TYPE_VOCAB, build_features


def _is_type_feature(col: str) -> bool:
    """Is this one of the frozen `type_*` one-hot columns (binary)?"""
    return col.startswith("type_") and col[len("type_"):] in TYPE_VOCAB


def _binary_edges() -> np.ndarray:
    """Two-bin edges for a 0/1-valued feature."""
    return np.array([-np.inf, 0.5, np.inf], dtype="float64")


def _binary_labels() -> tuple[str, ...]:
    return ("0", "1")


@dataclass(frozen=True)
class Distribution:
    """Binned reference distribution for one quantity.

    `edges` defines the bins; `counts` are the reference counts per bin;
    `labels` are human-readable bin names. The triple is what `psi()` needs.
    """

    edges: tuple[float, ...]
    counts: tuple[float, ...]
    labels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "edges": [_jsonable_edge(e) for e in self.edges],
            "counts": [float(c) for c in self.counts],
            "labels": list(self.labels),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Distribution":
        return cls(
            edges=tuple(_edge_from_jsonable(e) for e in payload["edges"]),
            counts=tuple(float(c) for c in payload["counts"]),
            labels=tuple(str(s) for s in payload["labels"]),
        )

    def counts_array(self) -> np.ndarray:
        return np.asarray(self.counts, dtype="float64")

    def edges_array(self) -> np.ndarray:
        return np.asarray(self.edges, dtype="float64")


def _jsonable_edge(value: float) -> Any:
    if value == float("inf"):
        return "inf"
    if value == float("-inf"):
        return "-inf"
    return float(value)


def _edge_from_jsonable(value: Any) -> float:
    if value == "inf":
        return float("inf")
    if value == "-inf":
        return float("-inf")
    return float(value)


@dataclass(frozen=True)
class BaselineSnapshot:
    """Frozen reference for a model version.

    `score` is the model output distribution; `features` is one Distribution
    per feature name (using the FEATURE_COLUMNS order).
    """

    model_version: str
    captured_at: str  # ISO-8601 UTC
    n_train: int
    score: Distribution
    features: dict[str, Distribution]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_version": self.model_version,
            "captured_at": self.captured_at,
            "n_train": self.n_train,
            "score": self.score.to_dict(),
            "features": {k: v.to_dict() for k, v in self.features.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BaselineSnapshot":
        return cls(
            model_version=str(payload["model_version"]),
            captured_at=str(payload["captured_at"]),
            n_train=int(payload["n_train"]),
            score=Distribution.from_dict(payload["score"]),
            features={
                name: Distribution.from_dict(p) for name, p in payload["features"].items()
            },
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "BaselineSnapshot":
        return cls.from_dict(json.loads(Path(path).read_text()))


def freeze_baseline(
    train_df: pd.DataFrame,
    *,
    model,
    model_version: str,
    n_bins: int = 10,
) -> BaselineSnapshot:
    """Compute the reference distributions over a training frame.

    Args:
        train_df: the raw training rows the model was fit on.
        model: a fitted classifier with `predict_proba`.
        model_version: tag baked into the snapshot for attribution.
        n_bins: quantile bins for numeric quantities (default deciles).

    Returns:
        A `BaselineSnapshot` ready to be `.save()`d alongside the model bundle.
    """
    feats = build_features(train_df)
    scores = model.predict_proba(feats)[:, 1]

    score_edges = quantile_bin_edges(scores, n_bins=n_bins)
    score_dist = Distribution(
        edges=tuple(score_edges),
        counts=tuple(bin_counts(scores, score_edges)),
        labels=edge_labels(score_edges),
    )

    feature_dists: dict[str, Distribution] = {}
    for col in FEATURE_COLUMNS:
        series = feats[col].to_numpy()
        if _is_type_feature(col):
            edges = _binary_edges()
            feature_dists[col] = Distribution(
                edges=tuple(edges),
                counts=tuple(bin_counts(series, edges)),
                labels=_binary_labels(),
            )
        else:
            edges = quantile_bin_edges(series, n_bins=n_bins)
            feature_dists[col] = Distribution(
                edges=tuple(edges),
                counts=tuple(bin_counts(series, edges)),
                labels=edge_labels(edges),
            )

    return BaselineSnapshot(
        model_version=model_version,
        captured_at=datetime.now(timezone.utc).isoformat(),
        n_train=int(len(train_df)),
        score=score_dist,
        features=feature_dists,
    )


def apply_score_bins(snapshot: BaselineSnapshot, scores: Sequence[float]) -> np.ndarray:
    """Bucket a stream of scores into the baseline's score bins."""
    return bin_counts(np.asarray(scores, dtype="float64"), snapshot.score.edges_array())


def apply_feature_bins(
    snapshot: BaselineSnapshot, feats: pd.DataFrame
) -> dict[str, np.ndarray]:
    """Bucket each feature column into its baseline bins, returning counts."""
    out: dict[str, np.ndarray] = {}
    for col, dist in snapshot.features.items():
        values = feats[col].to_numpy() if col in feats.columns else np.array([])
        out[col] = bin_counts(values, dist.edges_array())
    return out
