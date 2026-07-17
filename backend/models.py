"""Pydantic response/request schemas for the Sentinel API.

These mirror the Phase 2 metrics and Phase 3 memo/audit shapes so the React
dashboard has a stable contract independent of the storage backend.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# --- Health -------------------------------------------------------------


class BinReading(BaseModel):
    label: str
    expected_pct: float
    actual_pct: float
    signed_delta: float
    contribution: float


class PsiScore(BaseModel):
    value: float
    band: str          # stable | monitor | investigate
    color: str          # GREEN | AMBER | RED
    direction: str      # high | low | mid | stable
    bins: list[BinReading]


class FeatureCsi(BaseModel):
    feature: str
    value: float
    band: str


class HealthMetrics(BaseModel):
    n: int = 0
    positives: int = 0
    precision: float = 0.0
    recall: float = 0.0
    fpr: float = 0.0
    f1: float = 0.0


class Trend(BaseModel):
    status: str = "flat"      # rising | flat
    slope_per_day: float = 0.0
    signals: list[str] = []
    latest_value: float = 0.0


class FairnessRow(BaseModel):
    slice_value: str
    n: int
    fpr: float
    approval_rate: float
    fpr_gap: float
    approval_gap: float
    is_reference: bool = False


class Fairness(BaseModel):
    dataset: str = "baf"
    slice_column: str = ""
    rows: list[FairnessRow] = []


class HealthResponse(BaseModel):
    run_date: str | None = None
    model_version: str | None = None
    psi_score: PsiScore
    feature_csi: list[FeatureCsi] = []
    health: HealthMetrics = HealthMetrics()
    trend: Trend = Trend()
    fairness: Fairness = Fairness()


# --- Investigations / memos --------------------------------------------


class Citation(BaseModel):
    citation: str
    doc_id: str | None = None
    doc_title: str | None = None
    section_id: str | None = None
    section_title: str | None = None
    note: str | None = None
    score: float | None = None


class Memo(BaseModel):
    id: str | None = None
    finding: str
    business_implication: str
    policy_basis: str
    recommended_action: str
    citations: list[Citation] = []
    full_text: str
    color: str | None = None
    direction: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None


class InvestigationSummary(BaseModel):
    run_id: str
    run_date: str | None = None
    model_version: str | None = None
    color: str | None = None
    direction: str | None = None
    status: str               # pending_approval | approved | rejected | no_action
    created_at: str | None = None


class AgentRun(BaseModel):
    node: str
    seq: int
    n_citations: int = 0
    ts: str | None = None


class InvestigationDetail(BaseModel):
    run_id: str
    status: str
    breach_summary: str | None = None
    objective: str | None = None
    memo: Memo | None = None
    agent_runs: list[AgentRun] = []
    created_at: str | None = None


class TriggerRequest(BaseModel):
    # Optional; demo mode uses the current fixture breach when omitted.
    run_date: str | None = None
    model_version: str | None = None


class DecisionRequest(BaseModel):
    reviewer: str
    note: str | None = None


class AuditRow(BaseModel):
    ts: str | None = None
    kind: str | None = None
    actor: str | None = None
    action: str | None = None
    target: str | None = None
    citation: str | None = None
    node: str | None = None
    decision: str | None = None
    reviewer: str | None = None
    payload: dict[str, Any] = {}
