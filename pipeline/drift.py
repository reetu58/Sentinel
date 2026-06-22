"""Drift metrics — PSI, CSI, band-wise per-bin breakdowns, banding, direction.

CLAUDE.md conventions (non-negotiable):

- Bands: < 0.10 stable / GREEN, 0.10-0.25 monitor / AMBER, > 0.25 investigate / RED.
- PSI is read BAND-WISE (per-bin direction), not just the aggregate. A middling
  aggregate can hide a dangerous shift right at the decision boundary, so every
  drift result here carries per-bin `BinReading`s — expected%, actual%, signed
  delta, and that bin's PSI contribution — and a derived *direction*
  (`high` / `low` / `mid` / `stable`) that the Drafter agent later routes on.

Band thresholds and trend windows are read from `pipeline.config` so a single
place tunes them.

Pure, stateless, side-effect free. Everything here is unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from . import config

# --- Bands ---------------------------------------------------------------

#: Mapping of semantic band -> visual color used by the dashboard / memos.
BAND_COLORS: dict[str, str] = {
    "stable": "GREEN",
    "monitor": "AMBER",
    "investigate": "RED",
}


def band(psi_value: float) -> str:
    """Map a PSI/CSI value to its semantic band per CLAUDE.md."""
    if psi_value < config.PSI_BAND_MONITOR_MIN:
        return "stable"
    if psi_value < config.PSI_BAND_INVESTIGATE_MIN:
        return "monitor"
    return "investigate"


def band_color(band_name: str) -> str:
    """GREEN / AMBER / RED for a semantic band."""
    return BAND_COLORS[band_name]


# --- PSI / CSI math ------------------------------------------------------

#: Small floor added to each bin proportion to keep log(0) and divide-by-zero
#: from blowing up. Standard PSI hygiene; the same epsilon is applied to both
#: distributions so it cancels in the limit.
_EPS: float = 1e-6


def _safe_proportions(counts: np.ndarray) -> np.ndarray:
    counts = np.asarray(counts, dtype="float64")
    total = counts.sum()
    if total <= 0:
        # No observations -> uniform proportions, so PSI cleanly returns 0
        # against an identical distribution and a real value against any other.
        return np.full_like(counts, 1.0 / max(len(counts), 1))
    return counts / total


@dataclass(frozen=True)
class BinReading:
    """One row of the band-wise per-bin breakdown the dashboard renders."""

    label: str
    expected_pct: float  # proportion in reference distribution (0..1)
    actual_pct: float  # proportion in current distribution (0..1)
    signed_delta: float  # actual_pct - expected_pct  (>0 = gained mass)
    contribution: float  # this bin's contribution to the aggregate PSI

    def as_dict(self) -> dict[str, float | str]:
        return {
            "label": self.label,
            "expected_pct": self.expected_pct,
            "actual_pct": self.actual_pct,
            "signed_delta": self.signed_delta,
            "contribution": self.contribution,
        }


@dataclass(frozen=True)
class PSIResult:
    """Aggregate PSI plus the band-wise per-bin breakdown.

    Per-bin contributions sum to `value` within float tolerance. `bins` is the
    canonical payload persisted to the `psi_bins` table for the dashboard /
    agents to consume.
    """

    value: float
    bins: tuple[BinReading, ...]
    band: str  # "stable" | "monitor" | "investigate"
    color: str  # "GREEN" | "AMBER" | "RED"

    def __post_init__(self) -> None:
        total = sum(b.contribution for b in self.bins)
        if abs(total - self.value) > 1e-9:
            raise ValueError(
                f"PSI per-bin contributions ({total}) do not sum to aggregate "
                f"({self.value})."
            )


def psi(
    reference_counts: Sequence[float],
    current_counts: Sequence[float],
    *,
    bin_labels: Sequence[str] | None = None,
) -> PSIResult:
    """Population Stability Index between two binned distributions.

    Args:
        reference_counts: bin counts from the frozen baseline.
        current_counts: bin counts from the period under test. Must align
            one-for-one with `reference_counts`.
        bin_labels: optional human-readable labels for each bin (e.g. quantile
            ranges). Used in the per-bin breakdown.

    Returns:
        A `PSIResult` carrying the aggregate value, the per-bin breakdown
        (expected %, actual %, signed delta, contribution), and the band.
    """
    ref = np.asarray(reference_counts, dtype="float64")
    cur = np.asarray(current_counts, dtype="float64")
    if ref.shape != cur.shape:
        raise ValueError(
            f"reference and current counts must align: {ref.shape} vs {cur.shape}"
        )

    p_ref_raw = _safe_proportions(ref)
    p_cur_raw = _safe_proportions(cur)
    p_ref = p_ref_raw + _EPS
    p_cur = p_cur_raw + _EPS
    contributions = (p_cur - p_ref) * np.log(p_cur / p_ref)
    value = float(contributions.sum())

    labels = (
        tuple(bin_labels)
        if bin_labels is not None
        else tuple(f"bin_{i}" for i in range(len(ref)))
    )
    if len(labels) != len(ref):
        raise ValueError("bin_labels must have one entry per bin")

    bins = tuple(
        BinReading(
            label=labels[i],
            expected_pct=float(p_ref_raw[i]),
            actual_pct=float(p_cur_raw[i]),
            signed_delta=float(p_cur_raw[i] - p_ref_raw[i]),
            contribution=float(contributions[i]),
        )
        for i in range(len(ref))
    )

    band_name = band(value)
    return PSIResult(value=value, bins=bins, band=band_name, color=band_color(band_name))


# CSI is mathematically PSI applied to a feature; the alias keeps reader
# intent clear at call sites.
csi = psi


# --- Direction inference -------------------------------------------------


def direction(result: PSIResult) -> str:
    """Infer the routing direction from PSI per-bin signed deltas.

    Returns one of `stable`, `low`, `mid`, `high` (per CLAUDE.md's routing
    table). Only meaningful for the SCORE PSI; feature CSI directions aren't
    used for routing.

    NOTE: PSI *contributions* are always non-negative (they're a product of
    two factors that share sign), so they tell you HOW MUCH a bin deviated,
    not WHERE the current distribution actually gained mass. We localize using
    the **signed delta** (`actual_pct - expected_pct`) instead — splitting the
    ordered bins into thirds and picking the third with the largest positive
    signed delta. With < 3 bins we fall back to `mid`.
    """
    if result.band == "stable":
        return "stable"

    deltas = np.array([b.signed_delta for b in result.bins], dtype="float64")
    n = len(deltas)
    if n < 3:
        return "mid"

    third = n // 3
    low_mass = deltas[:third].sum()
    high_mass = deltas[-third:].sum()
    mid_mass = deltas[third : n - third].sum()

    masses = {"low": float(low_mass), "mid": float(mid_mass), "high": float(high_mass)}
    return max(masses, key=masses.get)


# --- Binning helpers (used by baseline + daily jobs) ---------------------


def quantile_bin_edges(values: np.ndarray, n_bins: int = 10) -> np.ndarray:
    """Compute monotonically increasing bin edges from quantiles.

    Duplicate quantile values (constant features) are collapsed so the edges
    are strictly increasing. The first and last edge are pushed to +/- inf so
    that out-of-range observations at serving time still land in the extreme
    bins instead of being dropped.
    """
    values = np.asarray(values, dtype="float64")
    values = values[~np.isnan(values)]
    if values.size == 0:
        return np.array([-np.inf, np.inf])

    qs = np.linspace(0.0, 1.0, n_bins + 1)
    edges = np.unique(np.quantile(values, qs))
    if edges.size < 2:
        # constant feature — manufacture a single-bin range
        edges = np.array([edges[0] - 1.0, edges[0] + 1.0])
    edges = edges.astype("float64")
    edges[0] = -np.inf
    edges[-1] = np.inf
    return edges


def bin_counts(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Count observations into bins defined by `edges` (left-inclusive)."""
    values = np.asarray(values, dtype="float64")
    values = values[~np.isnan(values)]
    counts, _ = np.histogram(values, bins=edges)
    return counts.astype("float64")


def edge_labels(edges: np.ndarray) -> tuple[str, ...]:
    """Human-readable labels for bins defined by `edges`."""
    out: list[str] = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        lo_s = "-inf" if np.isneginf(lo) else f"{lo:.4g}"
        hi_s = "inf" if np.isposinf(hi) else f"{hi:.4g}"
        out.append(f"[{lo_s}, {hi_s})")
    return tuple(out)
