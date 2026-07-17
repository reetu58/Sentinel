import React, { useState } from "react";

// Shows the Drafter's four-part memo and the human-gate controls. The memo
// content comes from the server; this component holds only ephemeral form
// state (reviewer, note, edit toggle) — never persisted client-side.

export default function CopilotPanel({ detail, reviewer, onReviewer, onDecide, busy }) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");

  if (!detail) {
    return (
      <div className="card copilot">
        <div className="card-title">Copilot</div>
        <div className="empty">Select or trigger an investigation to see the drafted memo.</div>
      </div>
    );
  }

  const memo = detail.memo;
  const decided = detail.status === "approved" || detail.status === "rejected";
  const pending = detail.status === "pending_approval";

  return (
    <div className="card copilot">
      <div className="card-title">
        Copilot memo
        <span className={`status status-${detail.status}`}>{detail.status}</span>
      </div>

      {detail.breach_summary && <p className="muted">{detail.breach_summary}</p>}

      {!memo ? (
        <div className="empty">No memo (breach was not material).</div>
      ) : (
        <div className="memo">
          <section>
            <h4>(a) Finding</h4>
            <p>{memo.finding}</p>
          </section>
          <section>
            <h4>(b) Business implication</h4>
            <p>{memo.business_implication}</p>
          </section>
          <section>
            <h4>(c) Policy basis</h4>
            <p>{memo.policy_basis}</p>
            <div className="cites">
              {(memo.citations || []).map((c) => (
                <span className="cite" key={c.citation} title={c.section_title || ""}>
                  {c.citation}
                </span>
              ))}
            </div>
          </section>
          <section>
            <h4>(d) Recommended action</h4>
            <p>{memo.recommended_action}</p>
          </section>

          <details className="rendered">
            <summary>Full rendered memo ({memo.llm_provider || "offline"})</summary>
            <pre>{memo.full_text}</pre>
          </details>
        </div>
      )}

      {memo && pending && (
        <div className="gate">
          <div className="gate-row">
            <label>
              Reviewer
              <input
                value={reviewer}
                onChange={(e) => onReviewer(e.target.value)}
                placeholder="human:you@bank.example"
              />
            </label>
            <button className="link" onClick={() => setEditing((v) => !v)}>
              {editing ? "Cancel edit" : "Edit note"}
            </button>
          </div>
          {editing && (
            <textarea
              className="note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Reviewer note (recorded with the decision in the audit log)"
            />
          )}
          <div className="gate-actions">
            <button
              className="btn btn-approve"
              disabled={busy || !reviewer}
              onClick={() => onDecide("approve", note)}
            >
              Approve
            </button>
            <button
              className="btn btn-reject"
              disabled={busy || !reviewer}
              onClick={() => onDecide("reject", note)}
            >
              Reject
            </button>
          </div>
          <p className="gate-note">
            Nothing ships without approval. Approve/Reject resumes the paused
            agent graph and appends the decision to the immutable audit log.
          </p>
        </div>
      )}

      {decided && (
        <p className="decided-banner">
          Decision recorded: <strong>{detail.status}</strong>. The agent graph
          has resumed and the audit log is updated.
        </p>
      )}
    </div>
  );
}
