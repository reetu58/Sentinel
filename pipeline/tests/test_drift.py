"""PSI / CSI / banding / direction tests."""

from __future__ import annotations

import math

import numpy as np
import pytest

from pipeline import drift
from pipeline.drift import band, band_color


def test_psi_identical_distributions_is_zero():
    result = drift.psi([10, 20, 30, 40], [10, 20, 30, 40])
    assert abs(result.value) < 1e-9
    assert result.band == "stable"
    assert result.color == "GREEN"


def test_psi_known_value():
    # Two-bin case with a hand-computable PSI.
    # ref proportions = [0.6, 0.4], cur = [0.4, 0.6]
    # PSI = (0.4-0.6)*ln(0.4/0.6) + (0.6-0.4)*ln(0.6/0.4)
    expected = (0.4 - 0.6) * math.log(0.4 / 0.6) + (0.6 - 0.4) * math.log(0.6 / 0.4)
    result = drift.psi([60, 40], [40, 60])
    assert result.value == pytest.approx(expected, rel=1e-4)


def test_psi_per_bin_sums_to_aggregate():
    result = drift.psi([10, 20, 30, 40, 50], [50, 40, 30, 20, 10])
    total = sum(b.contribution for b in result.bins)
    assert total == pytest.approx(result.value, rel=1e-9)


def test_psi_per_bin_payload_fields():
    result = drift.psi([50, 50], [80, 20])
    assert len(result.bins) == 2
    b0, b1 = result.bins
    assert b0.expected_pct == pytest.approx(0.5)
    assert b0.actual_pct == pytest.approx(0.8)
    assert b0.signed_delta == pytest.approx(0.3)
    assert b1.signed_delta == pytest.approx(-0.3)


def test_band_thresholds_match_claude_md():
    assert band(0.099) == "stable"
    assert band(0.10) == "monitor"
    assert band(0.24) == "monitor"
    assert band(0.25) == "investigate"
    assert band(1.0) == "investigate"


def test_band_color_mapping():
    assert band_color("stable") == "GREEN"
    assert band_color("monitor") == "AMBER"
    assert band_color("investigate") == "RED"


def test_direction_high_side_shift():
    # Score distribution gains mass in the top third -> "high" routing.
    # Shift is large enough that PSI clears the AMBER floor.
    ref = [100] * 10
    cur = [50, 50, 50, 50, 100, 100, 150, 150, 150, 150]
    result = drift.psi(ref, cur)
    assert result.band != "stable"
    assert drift.direction(result) == "high"


def test_direction_low_side_shift():
    ref = [100] * 10
    cur = [150, 150, 150, 150, 100, 100, 50, 50, 50, 50]
    result = drift.psi(ref, cur)
    assert result.band != "stable"
    assert drift.direction(result) == "low"


def test_direction_stable_when_stable():
    result = drift.psi([100, 100, 100], [101, 99, 100])
    assert result.band == "stable"
    assert drift.direction(result) == "stable"


def test_csi_alias_is_psi():
    assert drift.csi is drift.psi


def test_quantile_bin_edges_handles_constants():
    edges = drift.quantile_bin_edges(np.full(50, 3.14))
    assert edges.shape[0] >= 2
    assert math.isinf(edges[0]) and math.isinf(edges[-1])


def test_bin_counts_with_inf_edges_captures_outliers():
    edges = np.array([-np.inf, 0.0, 1.0, np.inf])
    counts = drift.bin_counts(np.array([-50.0, 0.5, 0.9, 999.0]), edges)
    # left bin gets -50, middle two get 0.5 + 0.9, right gets 999
    assert counts.tolist() == [1.0, 2.0, 1.0]


def test_psi_shape_mismatch_raises():
    with pytest.raises(ValueError):
        drift.psi([1, 2, 3], [1, 2])
