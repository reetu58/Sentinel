"""Health metrics + per-slice fairness tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.health import confusion, metrics, slice_metrics


def test_confusion_counts():
    labels = np.array([1, 1, 0, 0, 1, 0])
    preds = np.array([1, 0, 0, 1, 1, 0])
    c = confusion(labels, preds)
    assert (c.tp, c.fp, c.tn, c.fn) == (2, 1, 2, 1)
    assert c.total == 6


def test_metrics_known_case():
    labels = np.array([1, 1, 0, 0, 1, 0])
    preds = np.array([1, 0, 0, 1, 1, 0])
    m = metrics(labels, preds)
    # TP=2, FP=1, TN=2, FN=1 -> precision = 2/3, recall = 2/3, FPR = 1/3
    assert m.precision == pytest.approx(2 / 3)
    assert m.recall == pytest.approx(2 / 3)
    assert m.fpr == pytest.approx(1 / 3)
    assert m.f1 == pytest.approx(2 / 3)


def test_metrics_all_zero_predictions_doesnt_crash():
    labels = np.array([0, 0, 0, 1])
    preds = np.array([0, 0, 0, 0])
    m = metrics(labels, preds)
    assert m.precision == 0.0  # 0/0 guarded
    assert m.recall == 0.0
    assert m.fpr == 0.0


def test_slice_metrics_reports_per_slice_and_gaps():
    df = pd.DataFrame(
        {
            "label": [1, 0, 0, 1, 0, 0, 1, 0],
            "pred":  [1, 1, 0, 0, 0, 0, 1, 1],
            "group": ["A", "A", "A", "A", "B", "B", "B", "B"],
        }
    )
    sh = slice_metrics(df, label_col="label", pred_col="pred", slice_col="group")
    assert set(sh.per_slice.keys()) == {"A", "B"}
    # FPR for A: FP=1 (row 1), TN=1 (row 2)  -> FPR = 1/2
    assert sh.per_slice["A"].fpr == pytest.approx(0.5)
    # FPR for B: FP=1 (row 7), TN=2 (rows 4,5) -> FPR = 1/3
    assert sh.per_slice["B"].fpr == pytest.approx(1 / 3)
    # Gap is max abs difference from overall.
    assert sh.gaps["fpr"] >= 0.0


def test_slice_metrics_missing_column_raises():
    df = pd.DataFrame({"label": [0, 1], "pred": [0, 1]})
    with pytest.raises(KeyError):
        slice_metrics(df, label_col="label", pred_col="pred", slice_col="nope")
