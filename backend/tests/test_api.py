"""Backend API tests — the full human-in-the-loop, in demo mode.

Runs offline (no Postgres, no API key): demo repo + JSONL audit + deterministic
drafter. Each test uses isolated tmp paths for the audit log and checkpoint DB.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

# Isolate state BEFORE importing the app (config reads env at import time).
_TMP = Path(tempfile.mkdtemp(prefix="sentinel-api-"))
os.environ["SENTINEL_BACKEND_MODE"] = "demo"
os.environ["AUDIT_JSONL_PATH"] = str(_TMP / "audit.jsonl")
os.environ["AGENT_CHECKPOINT_DB"] = str(_TMP / "ckpt.sqlite")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_status_is_demo_offline(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "demo"
    assert body["llm"] == "offline"


def test_health_has_bandwise_psi_and_fairness(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    h = r.json()
    assert h["psi_score"]["color"] == "RED"
    assert h["psi_score"]["direction"] == "high"
    assert len(h["psi_score"]["bins"]) == 10  # band-wise breakdown present
    assert h["trend"]["status"] == "rising"
    assert any(row["slice_value"] == "65+" for row in h["fairness"]["rows"])


def test_full_loop_trigger_memo_approve_audit(client):
    # Trigger
    r = client.post("/api/investigations", json={})
    assert r.status_code == 200
    detail = r.json()
    run_id = detail["run_id"]
    assert detail["status"] == "pending_approval"
    memo = detail["memo"]
    assert memo["direction"] == "high"
    assert "Product / Sales / CX" in memo["business_implication"]
    assert [c["citation"] for c in memo["citations"]], "memo must be cited"

    # Queue shows it
    q = client.get("/api/investigations").json()
    assert any(i["run_id"] == run_id and i["status"] == "pending_approval" for i in q)

    # Approve resumes the graph
    r = client.post(f"/api/investigations/{run_id}/approve",
                    json={"reviewer": "human:test@bank.example", "note": "ok"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"

    # Re-approving is rejected (no longer awaiting)
    r = client.post(f"/api/investigations/{run_id}/approve",
                    json={"reviewer": "human:test@bank.example"})
    assert r.status_code == 409

    # Audit log carries the human decision
    audit = client.get("/api/audit?limit=50").json()
    assert any(a.get("decision") == "approved" for a in audit)
    assert any(a.get("actor") == "human:test@bank.example" for a in audit)


def test_reject_path(client):
    run_id = client.post("/api/investigations", json={}).json()["run_id"]
    r = client.post(f"/api/investigations/{run_id}/reject",
                    json={"reviewer": "human:risk@bank.example", "note": "seasonal"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


def test_unknown_run_id_404(client):
    r = client.get(f"/api/investigations/{uuid.uuid4()}")
    assert r.status_code == 404


def test_decide_unknown_run_409(client):
    r = client.post(f"/api/investigations/{uuid.uuid4()}/approve",
                    json={"reviewer": "human:x"})
    assert r.status_code == 409
