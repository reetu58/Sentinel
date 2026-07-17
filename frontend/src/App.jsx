import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import HealthTiles from "./components/HealthTiles.jsx";
import PsiBandChart from "./components/PsiBandChart.jsx";
import AlertQueue from "./components/AlertQueue.jsx";
import CopilotPanel from "./components/CopilotPanel.jsx";
import AuditTrail from "./components/AuditTrail.jsx";

export default function App() {
  const [status, setStatus] = useState(null);
  const [health, setHealth] = useState(null);
  const [queue, setQueue] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [audit, setAudit] = useState([]);
  const [reviewer, setReviewer] = useState("human:mrm@bank.example");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const refreshQueue = useCallback(async () => {
    setQueue(await api.listInvestigations());
  }, []);
  const refreshAudit = useCallback(async () => {
    setAudit(await api.audit(50));
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setStatus(await api.status());
        setHealth(await api.health());
        await refreshQueue();
        await refreshAudit();
      } catch (e) {
        setError(e.message);
      }
    })();
  }, [refreshQueue, refreshAudit]);

  useEffect(() => {
    if (!selectedId) return setDetail(null);
    api.getInvestigation(selectedId).then(setDetail).catch((e) => setError(e.message));
  }, [selectedId]);

  async function onTrigger() {
    setBusy(true);
    setError(null);
    try {
      const d = await api.trigger({});
      await refreshQueue();
      await refreshAudit();
      setSelectedId(d.run_id);
      setDetail(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onDecide(decision, note) {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    try {
      const fn = decision === "approve" ? api.approve : api.reject;
      const d = await fn(selectedId, reviewer, note);
      setDetail(d);
      await refreshQueue();
      await refreshAudit();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const psiColor = health?.psi_score?.color;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">🛡️ Sentinel <span className="sub">Fraud Model Risk Copilot</span></div>
        <div className="topbar-right">
          {status && (
            <span className="pill">
              mode: {status.mode} · llm: {status.llm}
            </span>
          )}
          <button className="btn btn-primary" onClick={onTrigger} disabled={busy}>
            {busy ? "Working…" : "Trigger investigation on current breach"}
          </button>
        </div>
      </header>

      {error && <div className="banner-error">⚠ {error}</div>}

      {health && (
        <div className={`breach-banner banner-${(psiColor || "").toLowerCase()}`}>
          {psiColor === "RED" || psiColor === "AMBER" ? (
            <>
              <strong>{psiColor} breach</strong> on {health.model_version} ·{" "}
              {health.run_date}: score PSI {health.psi_score.value.toFixed(4)} (
              {health.psi_score.direction}-side). Trend: {health.trend.status}.
            </>
          ) : (
            <>Model stable on {health.run_date}.</>
          )}
        </div>
      )}

      <HealthTiles health={health} />

      <div className="grid">
        <div className="col-left">
          {health && <PsiBandChart psi={health.psi_score} />}
          <AlertQueue items={queue} selectedId={selectedId} onSelect={setSelectedId} />
        </div>
        <div className="col-right">
          <CopilotPanel
            detail={detail}
            reviewer={reviewer}
            onReviewer={setReviewer}
            onDecide={onDecide}
            busy={busy}
          />
        </div>
      </div>

      <AuditTrail rows={audit} />

      <footer className="foot">
        Prototype · public/synthetic data · Sentinel assists a human model-risk
        manager — it never acts autonomously.
      </footer>
    </div>
  );
}
