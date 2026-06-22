"""Trend detector tests — sustained upward creep before a hard breach."""

from __future__ import annotations

import pytest

from pipeline.trend import detect


def test_flat_series_is_flat():
    flag = detect([0.05, 0.04, 0.05, 0.04])
    assert flag.status == "flat"
    assert flag.signals == ()


def test_monotone_rise_into_amber_flags_rising():
    # 0.05 -> 0.08 -> 0.11 -> 0.15: monotone, crosses the AMBER floor.
    flag = detect([0.05, 0.08, 0.11, 0.15])
    assert flag.status == "rising"
    assert "monotone_rising" in flag.signals
    assert "slope_positive" in flag.signals


def test_rising_below_amber_floor_stays_flat():
    # Even a clear creep stays "flat" if today's value is < 0.10. CLAUDE.md
    # bands a sub-0.10 reading as `stable` — no early warning yet.
    flag = detect([0.02, 0.03, 0.05, 0.07])
    assert flag.status == "flat"


def test_oscillation_does_not_flag_monotone():
    flag = detect([0.05, 0.08, 0.06, 0.12])
    assert "monotone_rising" not in flag.signals
    # Slope can still be positive enough to flag; that's intentional.


def test_window_is_respected():
    # An ancient spike followed by recent low values should not flag.
    flag = detect([0.30, 0.30, 0.04, 0.04, 0.05, 0.04], window=3)
    assert flag.status == "flat"


def test_empty_series_is_flat():
    flag = detect([])
    assert flag.status == "flat"
    assert flag.window_size == 0
