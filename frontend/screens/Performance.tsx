"use client";

type Range = "7D" | "30D" | "All";

interface Props {
  range: Range;
  onRange: (r: Range) => void;
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      border: `1px solid ${active ? "#111827" : "#D1D5DB"}`,
      background: active ? "#111827" : "#FFFFFF",
      color: active ? "#FFFFFF" : "#6B7280",
      fontSize: 11, fontWeight: 600, padding: "5px 12px",
      borderRadius: 6, cursor: "pointer", fontFamily: "inherit",
    }}>
      {label}
    </button>
  );
}

function EquityChart() {
  const pts = [0, 60, 35, 120, 95, 180, 230, 205, 290, 350, 420, 480, 540, 610, 690, 760, 830, 920, 1010, 1180];
  const W = 440, H = 180, PAD = 8;
  const max = Math.max(...pts), min = Math.min(...pts);
  const sx = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
  const sy = (v: number) => H - PAD - ((v - min) / (max - min)) * (H - PAD * 2);
  const line = pts.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)} ${sy(v).toFixed(1)}`).join(" ");
  const area = `${line} L${sx(pts.length - 1).toFixed(1)} ${H - PAD} L${sx(0).toFixed(1)} ${H - PAD} Z`;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      <defs>
        <linearGradient id="eqg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor="#16A34A" stopOpacity={0.18} />
          <stop offset="100%" stopColor="#16A34A" stopOpacity={0} />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((g, i) => (
        <line key={i} x1={PAD} x2={W - PAD}
          y1={PAD + g * (H - PAD * 2)} y2={PAD + g * (H - PAD * 2)}
          stroke="#F3F4F6" strokeWidth={1} />
      ))}
      <path d={area} fill="url(#eqg)" />
      <path d={line} fill="none" stroke="#16A34A" strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={sx(pts.length - 1)} cy={sy(pts[pts.length - 1])} r={4} fill="#16A34A" />
    </svg>
  );
}

function DonutChart() {
  const winPct = 68, r = 52, c = 2 * Math.PI * r;
  const offset = c * (1 - winPct / 100);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14 }}>
      <svg width={140} height={140} viewBox="0 0 140 140">
        <circle cx={70} cy={70} r={r} fill="none" stroke="#FEE2E2" strokeWidth={16} />
        <circle cx={70} cy={70} r={r} fill="none" stroke="#16A34A" strokeWidth={16}
          strokeDasharray={c} strokeDashoffset={offset}
          strokeLinecap="round" transform="rotate(-90 70 70)" />
        <text x={70} y={66} textAnchor="middle" fontSize={26} fontWeight={700} fill="#111827">68%</text>
        <text x={70} y={84} textAnchor="middle" fontSize={10} fill="#9CA3AF" letterSpacing=".05em">WIN RATE</text>
      </svg>
      <div style={{ display: "flex", gap: 16, fontSize: 11 }}>
        <span style={{ display: "flex", alignItems: "center", gap: 5, color: "#374151" }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "#16A34A", display: "inline-block" }} />
          97 Wins
        </span>
        <span style={{ display: "flex", alignItems: "center", gap: 5, color: "#374151" }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: "#FCA5A5", display: "inline-block" }} />
          45 Losses
        </span>
      </div>
    </div>
  );
}

function BarsChart() {
  const data = [
    { m: "Jan", v: 180 }, { m: "Feb", v: 240 }, { m: "Mar", v: -90 },
    { m: "Apr", v: 310 }, { m: "May", v: 160 }, { m: "Jun", v: 380 },
  ];

  const W = 440, H = 200;
  const padT = 28, padB = 26, padL = 8, padR = 8;
  const chartH = H - padT - padB;
  const chartW = W - padL - padR;

  const maxPos = Math.max(...data.map(d => Math.max(d.v, 0)), 1);
  const maxNeg = Math.max(...data.map(d => Math.max(-d.v, 0)), 1);
  const total  = maxPos + maxNeg;

  const baseline = padT + (maxPos / total) * chartH;
  const slotW    = chartW / data.length;
  const barW     = slotW * 0.52;

  const bx = (i: number) => padL + slotW * i + slotW / 2;
  const bh = (v: number) => (Math.abs(v) / total) * chartH;
  const by = (v: number) => v >= 0 ? baseline - bh(v) : baseline;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
      {/* Grid lines */}
      {[0.25, 0.5, 0.75].map((g, i) => (
        <line key={i} x1={padL} x2={W - padR}
          y1={padT + g * chartH} y2={padT + g * chartH}
          stroke="#F3F4F6" strokeWidth={1} />
      ))}
      {/* Zero baseline */}
      <line x1={padL} x2={W - padR} y1={baseline} y2={baseline}
        stroke="#E5E7EB" strokeWidth={1.5} />

      {data.map((d, i) => {
        const x   = bx(i);
        const h   = bh(d.v);
        const y   = by(d.v);
        const pos = d.v >= 0;
        return (
          <g key={i}>
            <rect x={x - barW / 2} y={y} width={barW} height={Math.max(h, 2)}
              fill={pos ? "#16A34A" : "#FCA5A5"} rx={3} />
            <text x={x} y={pos ? y - 5 : y + h + 11}
              textAnchor="middle" fontSize={10} fontWeight={600}
              fill={pos ? "#16A34A" : "#DC2626"}>
              {pos ? "+" : ""}{d.v}
            </text>
            <text x={x} y={H - 4} textAnchor="middle" fontSize={10} fill="#9CA3AF">
              {d.m}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function Performance({ range, onRange }: Props) {
  const netMap  = { "7D": "+$340", "30D": "+$1,180", "All": "+$4,860" };
  const cntMap  = { "7D": "24",    "30D": "142",     "All": "587" };
  const lblMap  = { "7D": "Last 7 days", "30D": "Last 30 days", "All": "All time" };

  return (
    <>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>Performance</div>
          <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>Equity growth &amp; trade quality</div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Chip label="7D"  active={range === "7D"}  onClick={() => onRange("7D")}  />
          <Chip label="30D" active={range === "30D"} onClick={() => onRange("30D")} />
          <Chip label="All" active={range === "All"} onClick={() => onRange("All")} />
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid-4">
        {[
          { label: "Net P&L",      value: netMap[range], color: "#16A34A" },
          { label: "Profit Factor", value: "2.34",       color: "#111827" },
          { label: "Total Trades",  value: cntMap[range], color: "#111827" },
          { label: "Max Drawdown",  value: "-4.8%",      color: "#DC2626" },
        ].map(c => (
          <div key={c.label} style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, padding: "12px 14px" }}>
            <div style={{ fontSize: 10, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 5 }}>{c.label}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: c.color }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* Equity curve + Donut */}
      <div className="grid-perf">
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Equity Curve</span>
            <span style={{ fontSize: 11, color: "#9CA3AF" }}>{lblMap[range]}</span>
          </div>
          <div style={{ padding: 16 }}><EquityChart /></div>
        </div>
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
          <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB" }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Win / Loss</span>
          </div>
          <div style={{ padding: 16, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
            <DonutChart />
          </div>
        </div>
      </div>

      {/* Monthly bars */}
      <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden" }}>
        <div style={{ padding: "12px 16px", borderBottom: "1px solid #E5E7EB" }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "#111827", textTransform: "uppercase", letterSpacing: ".05em" }}>Monthly P&L</span>
        </div>
        <div style={{ padding: 16 }}><BarsChart /></div>
      </div>
    </>
  );
}
