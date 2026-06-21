"""Phase 1 tests: the train/serve parity invariant and a train->score smoke."""

from __future__ import annotations

import pandas as pd

from pipeline.features import FEATURE_COLUMNS, build_features, build_features_one
from pipeline.sample_paysim import generate
from pipeline.scoring import ModelBundle
from pipeline.train_model import freeze, train


def test_feature_schema_is_frozen():
    df = generate(200, seed=1)
    feats = build_features(df)
    assert tuple(feats.columns) == FEATURE_COLUMNS
    assert feats.dtypes.eq("float64").all()


def test_train_serve_parity():
    """Batch featurization and single-record featurization must agree exactly.

    This is the skew Sentinel exists to catch; the scorer must not commit it.
    """
    df = generate(300, seed=2)
    batch = build_features(df)
    for i in range(0, len(df), 37):  # sample a spread of rows
        record = df.iloc[i].to_dict()
        one = build_features_one(record)
        pd.testing.assert_frame_equal(
            one.reset_index(drop=True),
            batch.iloc[[i]].reset_index(drop=True),
            check_dtype=True,
        )


def test_unknown_type_encodes_to_all_zero():
    df = pd.DataFrame([{"type": "TOTALLY_NEW_TYPE", "amount": 10.0}])
    feats = build_features(df)
    type_cols = [c for c in FEATURE_COLUMNS if c.startswith("type_")]
    assert feats[type_cols].to_numpy().sum() == 0.0


def test_train_and_score_roundtrip(tmp_path):
    df = generate(8_000, seed=3)
    model, metrics = train(df, seed=3, n_estimators=60)
    assert 0.0 <= metrics["pr_auc"] <= 1.0

    out = tmp_path / "fraud_xgb_v1.pkl"
    freeze(model, metrics, out, version="test")

    from pipeline.scoring import load_bundle

    bundle: ModelBundle = load_bundle(out)
    assert bundle.version == "test"
    assert tuple(bundle.feature_columns) == FEATURE_COLUMNS

    record = df.iloc[0].to_dict()
    score = bundle.score_record(record)
    assert 0.0 <= score <= 1.0

    # Frame scoring agrees with single-record scoring.
    frame_score = bundle.score_frame(df.iloc[[0]]).iloc[0]
    assert abs(frame_score - score) < 1e-9
