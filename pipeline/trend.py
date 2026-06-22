"""Trend detection — flag a sustained upward PSI rise BEFORE it crosses 0.25.

The brief calls this out specifically: a hard-threshold breach is too late.
A model whose score PSI marches from 0.04 -> 0.07 -> 0.11 -> 0.15 across four
days has *not* tripped the investigate band, but it is clearly drifting and
deserves an early warning.

Two complementary signals, both checked against the most recent N days:

1. `monotone_rising` — every step in the window is >= the previous one (a
   weak monotone increase), with the total delta exceeding a small minimum.
2. `slope_positive` — a least-squares slope over the window exceeds a small
   minimum-per-day rate.

A `TrendFlag` of `rising` is emitted if EITHER signal fires AND the current
value is in the AMBER band or higher. We never flag a stable-band trend as
"rising" — if PSI is < 0.10 and slowly creeping, that's normal noise.

Pure, stateless; all configuration lives in `pipeline.config`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from . import config
from .drift import band

#: A reading is "above the AMBER floor" (i.e. >= 0.10) when this returns True.
_ABOVE_STABLE = lambda v: band(v) != "stable"


@dataclass(frozen=True)
class TrendFlag:
    """Result of analyzing a window of recent PSI readings.

    `signals` is the set of detectors that fired (`monotone_rising`,
    `slope_positive`); `status` is `rising` if any signal fired and the latest
    value is at or above the AMBER floor, else `flat`.
    """

    status: str  # "rising" | "flat"
    signals: tuple[str, ...]
    slope_per_day: float
    window_size: int
    latest_value: float

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "signals": list(self.signals),
            "slope_per_day": self.slope_per_day,
            "window_size": self.window_size,
            "latest_value": self.latest_value,
        }


def detect(
    series: Sequence[float],
    *,
    window: int | None = None,
    min_total_delta: float | None = None,
    min_slope: float | None = None,
) -> TrendFlag:
    """Analyze the most recent `window` PSI readings.

    Args:
        series: chronologically ordered PSI values (oldest first, today last).
        window: how many trailing readings to consider (defaults to
            `config.TREND_WINDOW_DAYS`).
        min_total_delta: monotone signal requires the last value to exceed the
            first by at least this much (default `config.TREND_MIN_TOTAL_DELTA`).
        min_slope: slope signal requires least-squares slope per day to exceed
            this (default `config.TREND_MIN_SLOPE_PER_DAY`).

    Returns:
        A `TrendFlag` describing whether the series is "rising" and which
        signals fired.
    """
    window = window if window is not None else config.TREND_WINDOW_DAYS
    min_total_delta = (
        min_total_delta if min_total_delta is not None else config.TREND_MIN_TOTAL_DELTA
    )
    min_slope = min_slope if min_slope is not None else config.TREND_MIN_SLOPE_PER_DAY

    values = np.asarray(list(series), dtype="float64")
    if values.size == 0:
        return TrendFlag("flat", (), 0.0, 0, 0.0)
    tail = values[-window:]
    n = tail.size
    latest = float(tail[-1])

    signals: list[str] = []

    if n >= 2:
        diffs = np.diff(tail)
        if np.all(diffs >= 0) and (tail[-1] - tail[0]) >= min_total_delta:
            signals.append("monotone_rising")

    slope = 0.0
    if n >= 2:
        # Simple least-squares slope, x = 0..n-1 days.
        x = np.arange(n, dtype="float64")
        slope = float(np.polyfit(x, tail, 1)[0])
        if slope >= min_slope:
            signals.append("slope_positive")

    status = "rising" if signals and _ABOVE_STABLE(latest) else "flat"
    return TrendFlag(
        status=status,
        signals=tuple(signals),
        slope_per_day=slope,
        window_size=n,
        latest_value=latest,
    )
