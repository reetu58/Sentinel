"""Sentinel FastAPI backend — the human-in-the-loop made usable.

Routes:
  GET  /api/health              current daily PSI band + bins, CSI, FPR, fairness, trend
  GET  /api/investigations      the alert / investigation queue
  POST /api/investigations      trigger the agent graph on the current breach
  GET  /api/investigations/{id} one investigation (memo + status + agent runs)
  POST /api/investigations/{id}/approve   resume the graph; append decision to audit
  POST /api/investigations/{id}/reject    resume the graph; append decision to audit
  GET  /api/audit               the immutable audit log

All state is server-side. Secrets (LLM keys) come from .env via the router.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agents.audit import open_audit_sink
from agents.llm import LLMRouter
from rag.retriever import Retriever

from . import config
from .demo_data import load_demo_breach_metrics
from .models import (
    AuditRow,
    DecisionRequest,
    HealthResponse,
    InvestigationDetail,
    InvestigationSummary,
    TriggerRequest,
)
from .repository import DemoRepository, build_repository
from .service import AgentService, HumanGateError


@asynccontextmanager
async def lifespan(app: FastAPI):
    repo = build_repository()
    offline = repo.mode == "demo"
    corpus_dir = config.DEMO_CORPUS_DIR if offline else None
    retriever = (
        Retriever.from_corpus_dir(corpus_dir) if offline
        else Retriever.from_corpus_dir()
    )
    sink = open_audit_sink(offline=offline)
    service = AgentService(
        repo=repo, sink=sink, retriever=retriever,
        router=LLMRouter(), checkpoint_db=config.CHECKPOINT_DB,
    )
    app.state.repo = repo
    app.state.service = service
    app.state.mode = repo.mode
    yield


app = FastAPI(title="Sentinel API", version="0.4.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
def status() -> dict:
    return {"status": "ok", "mode": app.state.mode, "llm": app.state.service.router.provider}


@app.get("/api/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    try:
        return HealthResponse(**app.state.repo.get_health())
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/investigations", response_model=list[InvestigationSummary])
def list_investigations() -> list[InvestigationSummary]:
    out = []
    for d in app.state.repo.list_investigations():
        memo = d.get("memo") or {}
        out.append(InvestigationSummary(
            run_id=d["run_id"], run_date=d.get("run_date"),
            model_version=d.get("model_version"),
            color=(memo.get("color") if memo else d.get("color")),
            direction=(memo.get("direction") if memo else d.get("direction")),
            status=d["status"], created_at=d.get("created_at"),
        ))
    return out


@app.post("/api/investigations", response_model=InvestigationDetail)
def trigger_investigation(req: TriggerRequest) -> InvestigationDetail:
    svc: AgentService = app.state.service
    if app.state.mode == "demo":
        metrics = load_demo_breach_metrics()
    else:
        from agents.metrics_source import load_from_postgres
        from pipeline import config as pcfg

        if not req.run_date:
            health = app.state.repo.get_health()
            req.run_date = health["run_date"]
            req.model_version = req.model_version or health["model_version"]
        metrics = load_from_postgres(pcfg.POSTGRES_DSN, req.run_date, req.model_version or "v1")
    detail = svc.trigger(metrics)
    return InvestigationDetail(**detail)


@app.get("/api/investigations/{run_id}", response_model=InvestigationDetail)
def get_investigation(run_id: str) -> InvestigationDetail:
    d = app.state.repo.get_investigation(run_id)
    if not d:
        raise HTTPException(status_code=404, detail=f"unknown run_id {run_id}")
    return InvestigationDetail(**d)


def _decide(run_id: str, decision: str, req: DecisionRequest) -> InvestigationDetail:
    svc: AgentService = app.state.service
    try:
        detail = svc.decide(run_id, decision, reviewer=req.reviewer, note=req.note)
    except HumanGateError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return InvestigationDetail(**detail)


@app.post("/api/investigations/{run_id}/approve", response_model=InvestigationDetail)
def approve(run_id: str, req: DecisionRequest) -> InvestigationDetail:
    return _decide(run_id, "approve", req)


@app.post("/api/investigations/{run_id}/reject", response_model=InvestigationDetail)
def reject(run_id: str, req: DecisionRequest) -> InvestigationDetail:
    return _decide(run_id, "reject", req)


@app.get("/api/audit", response_model=list[AuditRow])
def get_audit(limit: int = 100) -> list[AuditRow]:
    rows = app.state.repo.get_audit(limit=limit)
    return [AuditRow(**_normalize_audit(r)) for r in rows]


def _normalize_audit(r: dict) -> dict:
    """Coerce a JSONL or DB audit record into the AuditRow shape."""
    return {
        "ts": r.get("ts"),
        "kind": r.get("kind"),
        "actor": r.get("actor"),
        "action": r.get("action"),
        "target": r.get("target"),
        "citation": r.get("citation"),
        "node": r.get("node"),
        "decision": r.get("decision"),
        "reviewer": r.get("reviewer"),
        "payload": r.get("payload") or {},
    }


# Serve the built React dashboard as static files when STATIC_DIR is set (the
# single-service Cloud Run deploy). Mounted LAST so the /api/* routes above
# always take precedence. Locally you instead run `npm run dev` (vite proxy).
if config.STATIC_DIR and Path(config.STATIC_DIR).is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=config.STATIC_DIR, html=True), name="static")
