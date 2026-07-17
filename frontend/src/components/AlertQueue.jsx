import React from "react";

const STATUS_LABEL = {
  pending_approval: "awaiting approval",
  approved: "approved",
  rejected: "rejected",
  no_action: "no action",
};

export default function AlertQueue({ items, selectedId, onSelect }) {
  return (
    <div className="card">
      <div className="card-title">Investigation queue</div>
      {items.length === 0 ? (
        <div className="empty">No investigations yet. Trigger one from a breach.</div>
      ) : (
        <ul className="queue">
          {items.map((it) => (
            <li
              key={it.run_id}
              className={`queue-item ${it.run_id === selectedId ? "active" : ""}`}
              onClick={() => onSelect(it.run_id)}
            >
              <span className={`dot dot-${(it.color || "").toLowerCase()}`} />
              <span className="queue-main">
                <span className="queue-id mono">{it.run_id.slice(0, 8)}</span>
                <span className="queue-meta">
                  {it.color} · {it.direction} · {it.run_date || ""}
                </span>
              </span>
              <span className={`status status-${it.status}`}>
                {STATUS_LABEL[it.status] || it.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
