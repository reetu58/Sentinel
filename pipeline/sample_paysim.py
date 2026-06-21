"""Generate a schema-accurate **synthetic** PaySim sample (tests / CI / demos).

This is fake, illustrative data — it resembles no real transactions. It exists
so the pipeline runs end-to-end without the Kaggle download. For real runs, use
the actual PaySim CSV (see docs/runbooks/data.md).

    python -m pipeline.sample_paysim --rows 20000 --out data/paysim.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

#: PaySim transaction types. Fraud occurs only in TRANSFER / CASH_OUT.
_TYPES = np.array(["PAYMENT", "TRANSFER", "CASH_OUT", "CASH_IN", "DEBIT"])
_FRAUD_TYPES = {"TRANSFER", "CASH_OUT"}


def generate(n: int = 20_000, *, seed: int = 7, fraud_rate: float = 0.012) -> pd.DataFrame:
    """Build a synthetic PaySim-shaped frame with a learnable fraud signal."""
    rng = np.random.default_rng(seed)

    type_p = np.array([0.34, 0.22, 0.22, 0.20, 0.02])
    txn_type = rng.choice(_TYPES, size=n, p=type_p)

    amount = rng.lognormal(mean=4.5, sigma=1.3, size=n).round(2)
    old_org = rng.lognormal(mean=5.0, sigma=1.5, size=n).round(2)

    # Fraud is a rare flag, only on TRANSFER/CASH_OUT, and in PaySim it tends to
    # drain the origin account (newbalanceOrig -> 0), which the error-balance
    # features pick up. We synthesize exactly that structure.
    eligible = np.isin(txn_type, list(_FRAUD_TYPES))
    is_fraud = (rng.random(n) < fraud_rate) & eligible

    new_org = np.where(is_fraud, 0.0, np.maximum(old_org - amount, 0.0)).round(2)

    old_dest = rng.lognormal(mean=4.0, sigma=1.6, size=n).round(2)
    # Legit transfers credit the destination; fraud often does not (mule churn).
    new_dest = np.where(is_fraud, old_dest, (old_dest + amount)).round(2)

    df = pd.DataFrame(
        {
            "step": rng.integers(1, 744, size=n),
            "type": txn_type,
            "amount": amount,
            "nameOrig": [f"C{i:09d}" for i in rng.integers(0, 10**9, size=n)],
            "oldbalanceOrg": old_org,
            "newbalanceOrig": new_org,
            "nameDest": [f"C{i:09d}" for i in rng.integers(0, 10**9, size=n)],
            "oldbalanceDest": old_dest,
            "newbalanceDest": new_dest,
            "isFraud": is_fraud.astype("int64"),
            "isFlaggedFraud": np.zeros(n, dtype="int64"),
        }
    )
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic PaySim CSV.")
    parser.add_argument("--rows", type=int, default=20_000)
    parser.add_argument("--out", type=Path, default=Path("data/paysim.csv"))
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    df = generate(args.rows, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df):,} synthetic rows -> {args.out} "
          f"(fraud: {int(df['isFraud'].sum())})")


if __name__ == "__main__":
    main()
