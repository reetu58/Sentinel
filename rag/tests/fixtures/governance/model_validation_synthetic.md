# Synthetic Model Validation Report — Fraud Scoring Model v1

> SYNTHETIC and illustrative only. Not a real validation of any deployed model.

## 1. Model overview

The model is a gradient-boosted decision tree (XGBoost) producing a fraud
probability for each transaction. The operating decision threshold is 0.85: a
transaction is flagged when the score is at or above 0.85.

## 2. Reference baseline

A frozen reference distribution of model scores and input features was captured
at training time and versioned with the model. All ongoing drift measurements
are computed against this baseline.

## 3. Monitoring thresholds

Population Stability Index bands are defined as: below 0.10 stable (green),
0.10 to 0.25 monitor (amber), and above 0.25 investigate (red). PSI is read
band-wise: the per-bin contribution is examined to locate where the
distribution has shifted, with particular attention to bins adjacent to the
0.85 decision threshold.

## 4. Known limitations

Results on public and synthetic data are illustrative and not deployable. The
validation does not constitute approval for production use. Material drift at or
above the red band, or a sustained upward trend approaching it, should be
escalated to model risk management for review.
