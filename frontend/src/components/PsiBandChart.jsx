import React from "react";

// Band-wise PSI breakdown: for each score bin, show expected% vs actual% as
// paired bars, colored by the direction of the shift (green = gained mass,
// red = lost mass). This is the core differentiator — a single PSI number
// hides WHERE the distribution moved; this shows it.

export default function PsiBandChart({ psi }) {
  if (!psi || !psi.bins) return null;
  const bins = psi.bins;
  const maxPct = Math.max(
    ...bins.map((b) => Math.max(b.expected_pct, b.actual_pct)),
    0.01
  );

  const W = 720;
  const H = 260;
  const padL = 40;
  const padB = 64;
  const padT = 16;
  const plotW = W - padL - 10;
  const plotH = H - padB - padT;
  const groupW = plotW / bins.length;
  const barW = Math.max(6, groupW / 2 - 3);

  const y = (pct) => padT + plotH - (pct / maxPct) * plotH;

  return (
    <div className="card">
      <div className="card-title">
        Band-wise PSI breakdown · score distribution
        <span className="legend">
          <span className="swatch swatch-exp" /> expected
          <span className="swatch swatch-act" /> actual
        </span>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} role="img"
           aria-label="Band-wise PSI breakdown">
        {/* baseline */}
        <line x1={padL} y1={padT + plotH} x2={W - 10} y2={padT + plotH}
              stroke="#3a4255" />
        {bins.map((b, i) => {
          const gx = padL + i * groupW;
          const gained = b.signed_delta >= 0;
          return (
            <g key={i}>
              <rect x={gx + 2} y={y(b.expected_pct)} width={barW}
                    height={padT + plotH - y(b.expected_pct)}
                    className="bar-exp" />
              <rect x={gx + 2 + barW + 2} y={y(b.actual_pct)} width={barW}
                    height={padT + plotH - y(b.actual_pct)}
                    className={gained ? "bar-gain" : "bar-loss"} />
              <text x={gx + groupW / 2} y={H - padB + 16} className="bin-x"
                    transform={`rotate(35 ${gx + groupW / 2} ${H - padB + 16})`}>
                {b.label}
              </text>
              <title>
                {`${b.label}\nexpected ${(b.expected_pct * 100).toFixed(2)}%  actual ${(b.actual_pct * 100).toFixed(2)}%\n` +
                  `delta ${(b.signed_delta * 100).toFixed(2)} pts  contribution ${b.contribution.toFixed(4)}`}
              </title>
            </g>
          );
        })}
      </svg>
      <table className="bin-table">
        <thead>
          <tr><th>bin</th><th>exp%</th><th>act%</th><th>Δ pts</th><th>contrib</th></tr>
        </thead>
        <tbody>
          {bins.map((b, i) => (
            <tr key={i} className={b.signed_delta >= 0 ? "row-gain" : "row-loss"}>
              <td className="mono">{b.label}</td>
              <td>{(b.expected_pct * 100).toFixed(2)}</td>
              <td>{(b.actual_pct * 100).toFixed(2)}</td>
              <td>{(b.signed_delta * 100 >= 0 ? "+" : "") + (b.signed_delta * 100).toFixed(2)}</td>
              <td>{b.contribution.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
