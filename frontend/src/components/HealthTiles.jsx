import React from "react";

const COLOR_CLASS = { GREEN: "tile-green", AMBER: "tile-amber", RED: "tile-red" };

function Tile({ label, value, sub, cls }) {
  return (
    <div className={`tile ${cls || ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

export default function HealthTiles({ health }) {
  if (!health) return null;
  const psi = health.psi_score;
  const h = health.health || {};
  const trend = health.trend || {};
  // Worst fairness FPR gap across slices.
  const rows = (health.fairness && health.fairness.rows) || [];
  const worst = rows
    .filter((r) => !r.is_reference)
    .reduce((m, r) => (Math.abs(r.fpr_gap) > Math.abs(m.fpr_gap || 0) ? r : m), {});

  return (
    <div className="tiles">
      <Tile
        label="Score PSI (band-wise)"
        value={psi.value.toFixed(4)}
        sub={`${psi.band} · direction: ${psi.direction}`}
        cls={COLOR_CLASS[psi.color]}
      />
      <Tile label="False-positive rate" value={(h.fpr ?? 0).toFixed(3)}
            sub={`precision ${(h.precision ?? 0).toFixed(2)} · recall ${(h.recall ?? 0).toFixed(2)}`} />
      <Tile
        label="Trend"
        value={trend.status === "rising" ? "RISING ↑" : "flat"}
        sub={`slope/day ${(trend.slope_per_day ?? 0).toFixed(4)}`}
        cls={trend.status === "rising" ? "tile-amber" : ""}
      />
      <Tile
        label="Worst fairness gap (FPR)"
        value={worst.slice_value ? `${worst.fpr_gap >= 0 ? "+" : ""}${worst.fpr_gap.toFixed(3)}` : "—"}
        sub={worst.slice_value ? `slice ${worst.slice_value} vs overall` : "no fairness data"}
        cls={Math.abs(worst.fpr_gap || 0) > 0.2 ? "tile-red" : ""}
      />
    </div>
  );
}
