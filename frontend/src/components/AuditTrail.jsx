import React from "react";

// Renders the immutable, append-only audit log straight from the API.

function describe(row) {
  if (row.kind === "decision")
    return { who: row.reviewer || "human", what: `decision: ${row.decision}`, cite: null };
  if (row.kind === "memo")
    return { who: "drafter_agent", what: "memo recorded", cite: null };
  if (row.kind === "agent_run")
    return { who: `${row.node || "node"}`, what: "agent run", cite: null };
  // plain audit row
  return { who: row.actor || "—", what: row.action || row.kind || "—", cite: row.citation };
}

export default function AuditTrail({ rows }) {
  return (
    <div className="card">
      <div className="card-title">Audit trail (append-only)</div>
      {(!rows || rows.length === 0) ? (
        <div className="empty">No audit entries yet.</div>
      ) : (
        <ul className="audit">
          {rows.map((r, i) => {
            const d = describe(r);
            const human = (d.who || "").startsWith("human");
            return (
              <li key={i} className={`audit-row ${human ? "audit-human" : ""}`}>
                <span className="audit-ts mono">
                  {(r.ts || "").replace("T", " ").slice(0, 19)}
                </span>
                <span className="audit-who">{d.who}</span>
                <span className="audit-what">{d.what}</span>
                {d.cite && <span className="cite small">{d.cite}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
