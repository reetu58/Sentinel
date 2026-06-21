# Data runbook

**Public datasets only. Real bank data is confidential and is never used.**
`data/` and `models/` are gitignored — never commit raw data or trained
artifacts. This repo is public.

## PaySim — the Phase 1 streaming spine

PaySim is a synthetic mobile-money dataset, fully labeled, ideal for replay.

1. Download from Kaggle (manual — do not script Kaggle auth here):
   <https://www.kaggle.com/datasets/ealaxi/paysim1>
2. Place the CSV at `data/paysim.csv` (the default path used by the pipeline).
   Override with the `PAYSIM_CSV` env var if you store it elsewhere.

Raw schema:

```
step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig,
nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud
```

The baseline reads a subset via `pipeline/features.py`; `nameOrig`/`nameDest`
identifiers are intentionally **not** used as features.

## Synthetic sample (tests / CI, no download)

To run the pipeline end-to-end without the Kaggle file, generate a small
schema-accurate synthetic PaySim sample:

```bash
python -m pipeline.sample_paysim --rows 20000 --out data/paysim.csv
```

This is **fake, illustrative data** — plausible ranges and a learnable
fraud signal, resembling no real transactions. The unit tests use it directly.

## Later phases

- **Bank Account Fraud Suite (NeurIPS 2022)** — Phase 2, for the fairness/bias
  audit (ships protected attributes; the EU AI Act angle).
- **IEEE-CIS Fraud Detection** — optional additional real-world stream.
