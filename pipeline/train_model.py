"""Train the XGBoost fraud baseline on PaySim and freeze a versioned artifact.

Run:
    python -m pipeline.train_model                  # uses data/paysim.csv
    python -m pipeline.train_model --data path.csv --out models/fraud_xgb_v1.pkl

Design notes:
- Features come ONLY from `pipeline.features.build_features` (train/serve parity).
- PaySim is heavily imbalanced (~0.13% fraud), so we set `scale_pos_weight` and
  evaluate with **PR-AUC** (average precision), not accuracy — accuracy is
  meaningless here. A classification report is printed at the 0.85 threshold.
- The frozen bundle records the feature schema, threshold, version, and metrics
  so the serving path can detect schema drift and the audit log can attribute
  every score to a specific model version.

`data/` and `models/` are gitignored; nothing here commits data or artifacts.
"""

from __future__ import annotations

import argparse
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    classification_report,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from . import config
from .features import FEATURE_COLUMNS, LABEL, build_features


def load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(
            f"PaySim CSV not found at {path}. Download it from Kaggle and place "
            "it there (see docs/runbooks/data.md). Data is never committed."
        )
    df = pd.read_csv(path)
    if LABEL not in df.columns:
        raise ValueError(f"dataset is missing the '{LABEL}' label column")
    return df


def train(
    df: pd.DataFrame,
    *,
    threshold: float = config.DECISION_THRESHOLD,
    seed: int = 42,
    n_estimators: int = 300,
) -> tuple[XGBClassifier, dict]:
    """Fit the baseline and return the model plus a metrics dict."""
    X = build_features(df)
    y = df[LABEL].astype(int)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=seed, stratify=y
    )

    n_pos = int(y_train.sum())
    n_neg = int(len(y_train) - n_pos)
    scale_pos_weight = (n_neg / n_pos) if n_pos else 1.0

    model = XGBClassifier(
        n_estimators=n_estimators,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.9,
        colsample_bytree=0.9,
        scale_pos_weight=scale_pos_weight,
        eval_metric="aucpr",
        tree_method="hist",
        n_jobs=-1,
        random_state=seed,
    )
    model.fit(X_train, y_train)

    proba = model.predict_proba(X_test)[:, 1]
    preds = (proba >= threshold).astype(int)

    pr_auc = float(average_precision_score(y_test, proba))
    roc_auc = float(roc_auc_score(y_test, proba)) if y_test.nunique() > 1 else float("nan")

    print(f"\nTrain rows: {len(X_train):,}  Test rows: {len(X_test):,}")
    print(f"Fraud prevalence (train): {n_pos}/{len(y_train)} "
          f"({100 * n_pos / max(len(y_train), 1):.3f}%)  scale_pos_weight={scale_pos_weight:.1f}")
    print(f"\nPR-AUC (average precision): {pr_auc:.4f}")
    print(f"ROC-AUC:                    {roc_auc:.4f}")
    print(f"\nClassification report @ threshold={threshold}:")
    print(classification_report(y_test, preds, digits=4, zero_division=0))

    metrics = {
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "threshold": threshold,
        "scale_pos_weight": scale_pos_weight,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "fraud_rate_train": float(n_pos / max(len(y_train), 1)),
    }
    return model, metrics


def freeze(model: XGBClassifier, metrics: dict, out_path: Path, *, version: str) -> None:
    """Pickle the model bundle with its schema, threshold, version, metrics."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bundle = {
        "model": model,
        "feature_columns": list(FEATURE_COLUMNS),
        "threshold": metrics["threshold"],
        "version": version,
        "metadata": {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "dataset": "PaySim",
            "metrics": metrics,
        },
    }
    with out_path.open("wb") as fh:
        pickle.dump(bundle, fh)
    print(f"\nFrozen model -> {out_path}  (version={version})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the PaySim XGBoost baseline.")
    parser.add_argument("--data", type=Path, default=config.DATA_PATH)
    parser.add_argument("--out", type=Path, default=config.MODEL_PATH)
    parser.add_argument("--threshold", type=float, default=config.DECISION_THRESHOLD)
    parser.add_argument("--version", type=str, default="v1")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    df = load_dataset(args.data)
    model, metrics = train(df, threshold=args.threshold, seed=args.seed)
    freeze(model, metrics, args.out, version=args.version)


if __name__ == "__main__":
    main()
