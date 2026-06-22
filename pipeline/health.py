"""Model health metrics: precision / recall / FPR + per-slice fairness gaps.

CLAUDE.md asks for daily health metrics alongside the drift signals (precision,
recall, FPR, plus fairness gaps across protected-attribute slices). Fairness
slicing here is parameterized on a slice column so it works for any future
dataset that ships a protected attribute (e.g. the Bank Account Fraud Suite).

Pure and stateless — given labels and predictions it returns dataclasses, with
no side effects. Decision-threshold logic lives in the *caller* (the scoring
path already thresholds; this module assumes preds are already 0/1).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Confusion:
    """Binary confusion matrix counts."""

    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn


@dataclass(frozen=True)
class HealthMetrics:
    """Headline classification metrics at a fixed decision threshold."""

    n: int
    positives: int
    precision: float
    recall: float
    fpr: float
    f1: float

    def as_dict(self) -> dict[str, float]:
        return {
            "n": float(self.n),
            "positives": float(self.positives),
            "precision": self.precision,
            "recall": self.recall,
            "fpr": self.fpr,
            "f1": self.f1,
        }


def confusion(labels: np.ndarray, preds: np.ndarray) -> Confusion:
    labels = np.asarray(labels).astype("int64")
    preds = np.asarray(preds).astype("int64")
    if labels.shape != preds.shape:
        raise ValueError(f"shape mismatch: labels={labels.shape} preds={preds.shape}")
    tp = int(((preds == 1) & (labels == 1)).sum())
    fp = int(((preds == 1) & (labels == 0)).sum())
    tn = int(((preds == 0) & (labels == 0)).sum())
    fn = int(((preds == 0) & (labels == 1)).sum())
    return Confusion(tp=tp, fp=fp, tn=tn, fn=fn)


def _safe_div(num: float, den: float) -> float:
    return float(num) / float(den) if den else 0.0


def metrics(labels: np.ndarray, preds: np.ndarray) -> HealthMetrics:
    """Compute precision / recall / FPR / F1 from binary predictions."""
    c = confusion(labels, preds)
    precision = _safe_div(c.tp, c.tp + c.fp)
    recall = _safe_div(c.tp, c.tp + c.fn)
    fpr = _safe_div(c.fp, c.fp + c.tn)
    f1 = _safe_div(2 * precision * recall, precision + recall)
    return HealthMetrics(
        n=c.total,
        positives=c.tp + c.fn,
        precision=precision,
        recall=recall,
        fpr=fpr,
        f1=f1,
    )


@dataclass(frozen=True)
class SliceHealth:
    """Per-slice health plus the largest gap vs the overall metric.

    The `gaps` dict reports `metric_name -> max(|slice_metric - overall|)` so
    a single number quantifies how unfair the model is on that metric, while
    `per_slice` keeps the full picture for the audit log.
    """

    overall: HealthMetrics
    per_slice: dict[str, HealthMetrics]
    gaps: dict[str, float]


def slice_metrics(
    df: pd.DataFrame,
    *,
    label_col: str,
    pred_col: str,
    slice_col: str,
) -> SliceHealth:
    """Compute overall + per-slice health metrics and the worst-case gap.

    `slice_col` is the protected attribute (e.g. age band, customer segment).
    Slices with zero rows are skipped; slices with no positives are kept and
    will report recall/F1 = 0 by definition.
    """
    if slice_col not in df.columns:
        raise KeyError(f"slice column '{slice_col}' not in DataFrame")

    overall = metrics(df[label_col].to_numpy(), df[pred_col].to_numpy())
    per_slice: dict[str, HealthMetrics] = {}
    for value, group in df.groupby(slice_col, dropna=False):
        if len(group) == 0:
            continue
        per_slice[str(value)] = metrics(
            group[label_col].to_numpy(),
            group[pred_col].to_numpy(),
        )

    # Worst-case gap per metric: max across slices of |slice_value - overall|.
    metric_names = ("precision", "recall", "fpr", "f1")
    gaps: dict[str, float] = {}
    for name in metric_names:
        if not per_slice:
            gaps[name] = 0.0
            continue
        overall_v = getattr(overall, name)
        gaps[name] = max(abs(getattr(m, name) - overall_v) for m in per_slice.values())

    return SliceHealth(overall=overall, per_slice=per_slice, gaps=gaps)
