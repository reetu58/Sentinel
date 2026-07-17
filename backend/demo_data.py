"""Demo-mode data: a full health response built from the breach fixture.

Lets the backend (and the dashboard) run the whole loop with nothing in
Postgres and no governance corpus placed — the same offline philosophy as the
Phase 3 agent CLI. The fairness rows mirror the Phase 2 BAF audit output.
"""

from __future__ import annotations

import json
from typing import Any

from . import config


def load_demo_health() -> dict[str, Any]:
    """Assemble a HealthResponse-shaped dict from the demo breach fixture."""
    breach = json.loads(config.DEMO_BREACH_FILE.read_text())
    score = breach["score_psi"]
    return {
        "run_date": breach.get("run_date"),
        "model_version": breach.get("model_version"),
        "psi_score": {
            "value": score["value"],
            "band": score["band"],
            "color": score["color"],
            "direction": score["direction"],
            "bins": score["bins"],
        },
        "feature_csi": breach.get("feature_csi", []),
        "health": breach.get("health", {}),
        "trend": breach.get("trend", {}),
        "fairness": {
            "dataset": "baf",
            "slice_column": "customer_age",
            # Illustrative gaps mirroring the Phase 2 fairness verification:
            # older cohorts are disproportionately false-flagged.
            "rows": [
                {"slice_value": "(overall)", "n": 4500, "fpr": 0.4200,
                 "approval_rate": 0.5653, "fpr_gap": 0.0, "approval_gap": 0.0,
                 "is_reference": True},
                {"slice_value": "<25", "n": 473, "fpr": 0.0131,
                 "approval_rate": 0.9873, "fpr_gap": -0.4069, "approval_gap": 0.4220,
                 "is_reference": False},
                {"slice_value": "25-34", "n": 631, "fpr": 0.0461,
                 "approval_rate": 0.9556, "fpr_gap": -0.3739, "approval_gap": 0.3903,
                 "is_reference": False},
                {"slice_value": "35-49", "n": 1039, "fpr": 0.1949,
                 "approval_rate": 0.7988, "fpr_gap": -0.2251, "approval_gap": 0.2335,
                 "is_reference": False},
                {"slice_value": "50-64", "n": 1025, "fpr": 0.5183,
                 "approval_rate": 0.4712, "fpr_gap": 0.0983, "approval_gap": -0.0941,
                 "is_reference": False},
                {"slice_value": "65+", "n": 1332, "fpr": 0.8724,
                 "approval_rate": 0.1209, "fpr_gap": 0.4524, "approval_gap": -0.4445,
                 "is_reference": False},
            ],
        },
    }


def load_demo_breach_metrics() -> dict[str, Any]:
    """The metrics dict the agent graph consumes when triggered in demo mode."""
    return json.loads(config.DEMO_BREACH_FILE.read_text())
