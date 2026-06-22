"""Baseline freeze/load + PSI-against-baseline tests.

Trains a tiny model on the synthetic PaySim generator, freezes the baseline,
then verifies that scoring the same training frame at "today" yields a near-
zero PSI (no drift), while scoring a fraud-skewed sample lights up.
"""

from __future__ import annotations

import pandas as pd

from pipeline.baseline import BaselineSnapshot, apply_score_bins, freeze_baseline
from pipeline.drift import psi
from pipeline.features import FEATURE_COLUMNS, build_features
from pipeline.sample_paysim import generate
from pipeline.train_model import train


def _fit_small_model(seed: int):
    df = generate(6_000, seed=seed)
    model, _ = train(df, seed=seed, n_estimators=40)
    return df, model


def test_baseline_round_trip(tmp_path):
    df, model = _fit_small_model(seed=11)
    snap = freeze_baseline(df, model=model, model_version="test")
    path = tmp_path / "baseline.json"
    snap.save(path)

    reloaded = BaselineSnapshot.load(path)
    assert reloaded.model_version == "test"
    assert reloaded.n_train == len(df)
    assert tuple(reloaded.features.keys()) == tuple(FEATURE_COLUMNS)
    # bin edges round-trip including infinities
    assert reloaded.score.edges[0] == float("-inf")
    assert reloaded.score.edges[-1] == float("inf")


def test_score_psi_against_self_is_near_zero():
    df, model = _fit_small_model(seed=13)
    snap = freeze_baseline(df, model=model, model_version="test")
    scores_today = model.predict_proba(build_features(df))[:, 1]
    counts_today = apply_score_bins(snap, scores_today)
    result = psi(snap.score.counts_array(), counts_today, bin_labels=snap.score.labels)
    assert result.value < 0.01  # essentially no drift against the training frame
    assert result.band == "stable"


def test_score_psi_against_fraud_heavy_sample_drifts_high():
    df, model = _fit_small_model(seed=17)
    snap = freeze_baseline(df, model=model, model_version="test")
    # Take a fraud-skewed sample: keep only the fraud rows + a small legit tail.
    fraud = df[df.isFraud == 1]
    skewed = pd.concat([fraud] * 10 + [df[df.isFraud == 0].head(50)], ignore_index=True)
    scores = model.predict_proba(build_features(skewed))[:, 1]
    counts_today = apply_score_bins(snap, scores)
    result = psi(snap.score.counts_array(), counts_today, bin_labels=snap.score.labels)
    assert result.value > 0.10  # at minimum lands in the monitor band
