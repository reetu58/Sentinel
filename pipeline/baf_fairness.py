"""Bank Account Fraud Suite — fairness audit.

A separate, self-contained module from the PaySim flow. Loads the BAF CSV
(public data, never committed — see docs/runbooks/data.md), trains a quick
fraud model on it, then computes per-group **false-positive rate** and
**approval-rate gaps** across protected attributes. Results land in the
`fairness_metrics` table for the dashboard / agents.

Approval rate = share of applications the model lets through (1 - flag rate).
Gaps are reported against the overall reference slice: `gap_<slice_value>
= metric(slice) - metric(overall)`, so a positive FPR gap means a group is
*disproportionately* false-flagged.

Run:
    python -m pipeline.baf_fairness --slice customer_age
    python -m pipeline.baf_fairness --slice employment_status --dry-run
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from . import config
from .db import connect
from .health import metrics

DATASET_NAME = "baf"
MODEL_VERSION = "baf_logreg_v1"

#: BAF columns the audit defaults to slicing on. Order matters: the first
#: present column is used unless --slice overrides. All are protected /
#: sensitive attributes per the BAF paper.
DEFAULT_SLICE_CANDIDATES: tuple[str, ...] = (
    "customer_age",
    "employment_status",
    "income",
    "housing_status",
)

#: BAF label.
LABEL: str = "fraud_bool"


@dataclass(frozen=True)
class FairnessRow:
    dataset: str
    slice_column: str
    slice_value: str
    n: int
    positives: int
    fpr: float
    approval_rate: float
    precision: float
    recall: float
    f1: float
    is_reference: bool


def _band_age(values: pd.Series) -> pd.Series:
    """BAF `customer_age` is continuous; band it into the standard cohorts."""
    bins = [-np.inf, 25, 35, 50, 65, np.inf]
    labels = ["<25", "25-34", "35-49", "50-64", "65+"]
    return pd.cut(values, bins=bins, labels=labels, right=False).astype("string")


def _prepare_slice(df: pd.DataFrame, slice_col: str) -> pd.Series:
    """Coerce a slice column into a string categorical the audit can group on."""
    if slice_col not in df.columns:
        raise KeyError(f"slice column '{slice_col}' not in BAF frame")
    s = df[slice_col]
    if slice_col == "customer_age" and pd.api.types.is_numeric_dtype(s):
        return _band_age(s)
    return s.astype("string").fillna("(missing)")


def _pick_slice(df: pd.DataFrame, requested: str | None) -> str:
    if requested:
        return requested
    for cand in DEFAULT_SLICE_CANDIDATES:
        if cand in df.columns:
            return cand
    raise ValueError(
        "no usable slice column in BAF frame; pass --slice. Tried: "
        f"{list(DEFAULT_SLICE_CANDIDATES)}"
    )


def _train_baf_model(df: pd.DataFrame, threshold: float, *, seed: int = 42):
    """Train a quick logistic-regression baseline on BAF.

    We deliberately keep this small and obviously-replicable: the fairness
    audit isn't about the model's PR-AUC, it's about showing the gaps any
    half-decent classifier would inherit from the data.
    """
    feats = df.drop(columns=[LABEL]).copy()
    feats = pd.get_dummies(feats, drop_first=True, dummy_na=True)
    feats = feats.fillna(0.0).astype("float64")
    y = df[LABEL].astype(int)

    X_train, X_test, y_train, y_test, _, idx_test = train_test_split(
        feats, y, np.arange(len(df)), test_size=0.3, random_state=seed, stratify=y
    )
    scaler = StandardScaler(with_mean=False)
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)

    model = LogisticRegression(
        max_iter=400, class_weight="balanced", solver="lbfgs", random_state=seed
    )
    model.fit(X_train_s, y_train)
    proba = model.predict_proba(X_test_s)[:, 1]
    preds = (proba >= threshold).astype(int)
    return preds, y_test.to_numpy(), idx_test


def audit(
    df: pd.DataFrame,
    *,
    slice_column: str,
    threshold: float = 0.5,
    seed: int = 42,
) -> list[FairnessRow]:
    """Run the BAF fairness audit and return one `FairnessRow` per slice value.

    The first row is the **reference** (`is_reference=True`) — the overall
    population. Subsequent rows are per-slice; gaps are reported against the
    reference row by the persistence layer / dashboard.
    """
    if LABEL not in df.columns:
        raise ValueError(f"BAF frame is missing the '{LABEL}' label column")

    preds, y_true, idx_test = _train_baf_model(df, threshold, seed=seed)
    test_view = df.iloc[idx_test].reset_index(drop=True).copy()
    test_view["__pred__"] = preds
    test_view["__label__"] = y_true
    test_view["__slice__"] = _prepare_slice(test_view, slice_column).to_numpy()

    rows: list[FairnessRow] = []

    overall_m = metrics(test_view["__label__"].to_numpy(), test_view["__pred__"].to_numpy())
    rows.append(
        FairnessRow(
            dataset=DATASET_NAME,
            slice_column=slice_column,
            slice_value="(overall)",
            n=overall_m.n,
            positives=int(overall_m.positives),
            fpr=overall_m.fpr,
            approval_rate=_approval_rate(test_view["__pred__"]),
            precision=overall_m.precision,
            recall=overall_m.recall,
            f1=overall_m.f1,
            is_reference=True,
        )
    )

    for value, group in test_view.groupby("__slice__", dropna=False):
        if len(group) == 0:
            continue
        m = metrics(group["__label__"].to_numpy(), group["__pred__"].to_numpy())
        rows.append(
            FairnessRow(
                dataset=DATASET_NAME,
                slice_column=slice_column,
                slice_value=str(value),
                n=m.n,
                positives=int(m.positives),
                fpr=m.fpr,
                approval_rate=_approval_rate(group["__pred__"]),
                precision=m.precision,
                recall=m.recall,
                f1=m.f1,
                is_reference=False,
            )
        )
    return rows


def _approval_rate(preds: Sequence[int]) -> float:
    arr = np.asarray(list(preds), dtype="int64")
    if arr.size == 0:
        return 0.0
    return float((arr == 0).sum() / arr.size)


def render(rows: list[FairnessRow]) -> str:
    """Human-readable summary, including gaps vs the reference row."""
    if not rows:
        return "(no fairness rows)"
    overall = next((r for r in rows if r.is_reference), rows[0])

    lines: list[str] = []
    lines.append(
        f"\n== Fairness audit  dataset={DATASET_NAME}  "
        f"slice={overall.slice_column}  model={MODEL_VERSION} =="
    )
    lines.append(
        f"{'slice':<14} {'n':>7} {'fpr':>8} {'approval':>10} "
        f"{'fpr_gap':>9} {'appr_gap':>10}"
    )
    for r in rows:
        fpr_gap = 0.0 if r.is_reference else r.fpr - overall.fpr
        appr_gap = 0.0 if r.is_reference else r.approval_rate - overall.approval_rate
        marker = "*" if r.is_reference else " "
        lines.append(
            f"{marker}{r.slice_value:<13} {r.n:>7} {r.fpr:>8.4f} "
            f"{r.approval_rate:>10.4f} {fpr_gap:>+9.4f} {appr_gap:>+10.4f}"
        )
    lines.append("\n* = reference (overall population)")
    return "\n".join(lines)


def persist(dsn: str, rows: list[FairnessRow], run_date: date) -> None:
    """Idempotently UPSERT a day's fairness rows into Postgres."""
    if not rows:
        return
    sql = """
        INSERT INTO fairness_metrics
            (run_date, dataset, model_version, slice_column, slice_value,
             n, positives, fpr, approval_rate, precision, recall, f1,
             is_reference, payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (run_date, dataset, model_version, slice_column, slice_value)
        DO UPDATE SET n = EXCLUDED.n,
                      positives = EXCLUDED.positives,
                      fpr = EXCLUDED.fpr,
                      approval_rate = EXCLUDED.approval_rate,
                      precision = EXCLUDED.precision,
                      recall = EXCLUDED.recall,
                      f1 = EXCLUDED.f1,
                      is_reference = EXCLUDED.is_reference,
                      payload = EXCLUDED.payload
    """
    overall = next((r for r in rows if r.is_reference), rows[0])
    with connect(dsn) as conn, conn.cursor() as cur:
        for r in rows:
            payload = {
                "precision": r.precision,
                "recall": r.recall,
                "f1": r.f1,
                "fpr_gap_vs_overall": 0.0 if r.is_reference else r.fpr - overall.fpr,
                "approval_gap_vs_overall": (
                    0.0 if r.is_reference else r.approval_rate - overall.approval_rate
                ),
            }
            cur.execute(
                sql,
                (
                    run_date,
                    r.dataset,
                    MODEL_VERSION,
                    r.slice_column,
                    r.slice_value,
                    r.n,
                    r.positives,
                    r.fpr,
                    r.approval_rate,
                    r.precision,
                    r.recall,
                    r.f1,
                    r.is_reference,
                    json.dumps(payload),
                ),
            )

        cur.execute(
            """
            INSERT INTO audit_log (actor, action, target, citation, payload)
            VALUES (%s, %s, %s, %s, %s::jsonb)
            """,
            (
                "baf_fairness_job",
                "compute_fairness_audit",
                f"fairness_metrics:{run_date}/{DATASET_NAME}/{overall.slice_column}",
                "EU_AI_Act:high-risk_obligations",
                json.dumps(
                    {
                        "slice_column": overall.slice_column,
                        "rows": len(rows) - 1,
                        "worst_fpr_gap": max(
                            (abs(r.fpr - overall.fpr) for r in rows if not r.is_reference),
                            default=0.0,
                        ),
                    }
                ),
            ),
        )
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BAF fairness audit.")
    parser.add_argument("--data", type=Path, default=config.BAF_CSV)
    parser.add_argument("--slice", dest="slice_col", default=None,
                        help="Protected attribute to slice on (default: auto-pick).")
    parser.add_argument("--threshold", type=float, default=0.5)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--dsn", default=config.POSTGRES_DSN)
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Postgres writes; print the gap table.")
    args = parser.parse_args()

    if not args.data.exists():
        raise SystemExit(
            f"BAF CSV not found at {args.data}. Public dataset — see "
            "docs/runbooks/data.md for how to obtain it."
        )

    df = pd.read_csv(args.data)
    slice_col = _pick_slice(df, args.slice_col)
    rows = audit(df, slice_column=slice_col, threshold=args.threshold)
    print(render(rows))

    if not args.dry_run:
        persist(args.dsn, rows, date.fromisoformat(args.date))


if __name__ == "__main__":
    main()
