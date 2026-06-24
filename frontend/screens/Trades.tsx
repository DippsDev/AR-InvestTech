"use client";
import type { Trade } from "@/lib/api";

type Filter = "all" | "win" | "loss";

interface Props {
  trades: Trade[];
  filter: Filter;
  onFilter: (f: Filter) => void;
}

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{
      border: `1px solid ${active ? "#111827" : "#D1D5DB"}`,
      background: active ? "#111827" : "#FFFFFF",
      color: active ? "#FFFFFF" : "#6B7280",
      fontSize: 11,
      fontWeight: 600,
      padding: "5px 12px",
      borderRadius: 6,
      cursor: "pointer",
      fontFamily: "inherit",
    }}>
      {label}
    </button>
  );
}

export default function Trades({ trades, filter, onFilter }: Props) {
  const visible = filter === "win"
    ? trades.filter(t => t.win)
    : filter === "loss"
    ? trades.filter(t => !t.win)
    : trades;

  const wins   = visible.filter(t => t.win).length;
  const losses = visible.length - wins;
  const net    = visible.reduce((a, t) => a + t.pnl, 0);

  return (
    <>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>Trades</div>
          <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>Closed positions · last 30 days</div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <Chip label="All"    active={filter === "all"}  onClick={() => onFilter("all")}  />
          <Chip label="Wins"   active={filter === "win"}  onClick={() => onFilter("win")}  />
          <Chip label="Losses" active={filter === "loss"} onClick={() => onFilter("loss")} />
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid-4">
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, padding: "12px 14px" }}>
          <div style={{ fontSize: 10, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 5 }}>Showing</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#111827" }}>{visible.length}</div>
        </div>
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, padding: "12px 14px" }}>
          <div style={{ fontSize: 10, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 5 }}>Wins</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#16A34A" }}>{wins}</div>
        </div>
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, padding: "12px 14px" }}>
          <div style={{ fontSize: 10, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 5 }}>Losses</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#DC2626" }}>{losses}</div>
        </div>
        <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, padding: "12px 14px" }}>
          <div style={{ fontSize: 10, color: "#9CA3AF", textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 5 }}>Net P&L</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: net >= 0 ? "#16A34A" : "#DC2626" }}>
            {net >= 0 ? "+" : "-"}${Math.abs(net).toFixed(2)}
          </div>
        </div>
      </div>

      {/* Mobile cards (≤768px) */}
      <div className="trade-cards">
        {visible.map(t => (
          <div key={`card-${t.id}`} style={{
            background: "#FFFFFF",
            border: `1px solid ${t.win ? "#D1FAE5" : "#FEE2E2"}`,
            borderRadius: 8,
            padding: "12px 14px",
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <div>
                <div style={{ fontSize: 12, fontWeight: 700, color: "#111827" }}>{t.id}</div>
                <div style={{ fontSize: 11, color: "#6B7280", marginTop: 2 }}>{t.date} · {t.lots} lots</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: t.win ? "#16A34A" : "#DC2626" }}>
                  {t.pnl >= 0 ? "+$" : "-$"}{Math.abs(t.pnl).toFixed(2)}
                </div>
                <div style={{ fontSize: 11, color: t.win ? "#16A34A" : "#DC2626", marginTop: 2 }}>{t.pips} pips</div>
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 8, paddingTop: 8, borderTop: "1px solid #F3F4F6", fontSize: 11 }}>
              <span style={{ fontWeight: 700, color: t.side === "BUY" ? "#16A34A" : "#DC2626" }}>{t.side}</span>
              <span style={{ color: "#9CA3AF" }}>{t.entry} → {t.exit}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Desktop table (>768px) */}
      <div style={{ background: "#FFFFFF", border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden", overflowX: "auto" }}>
        <div className="tbl-wrap">
        {/* Header row */}
        <div className="tbl-row" style={{
          display: "grid",
          gridTemplateColumns: "92px 70px 48px 52px 80px 80px 56px 1fr",
          gap: 8,
          padding: "10px 16px",
          borderBottom: "1px solid #E5E7EB",
          fontSize: 10,
          color: "#9CA3AF",
          textTransform: "uppercase",
          letterSpacing: ".04em",
        }}>
          <span>Trade</span><span>Date</span><span>Side</span><span>Lots</span>
          <span>Entry</span><span>Exit</span><span>Pips</span>
          <span style={{ textAlign: "right" }}>P&L</span>
        </div>
        {/* Data rows */}
        {visible.map(t => (
          <div key={t.id} className="animate-row-in tbl-row" style={{
            display: "grid",
            gridTemplateColumns: "92px 70px 48px 52px 80px 80px 56px 1fr",
            gap: 8,
            padding: "9px 16px",
            borderBottom: "1px solid #F3F4F6",
            fontSize: 12,
            alignItems: "center",
          }}>
            <span style={{ fontWeight: 600, color: "#111827" }}>{t.id}</span>
            <span style={{ color: "#6B7280" }}>{t.date}</span>
            <span style={{ fontWeight: 700, fontSize: 11, color: t.side === "BUY" ? "#16A34A" : "#DC2626" }}>{t.side}</span>
            <span style={{ color: "#6B7280" }}>{t.lots}</span>
            <span style={{ color: "#374151" }}>{t.entry}</span>
            <span style={{ color: "#374151" }}>{t.exit}</span>
            <span style={{ color: t.win ? "#16A34A" : "#DC2626" }}>{t.pips}</span>
            <span style={{ textAlign: "right", fontWeight: 600, color: t.win ? "#16A34A" : "#DC2626" }}>
              {t.pnl >= 0 ? "+$" : "-$"}{Math.abs(t.pnl).toFixed(2)}
            </span>
          </div>
        ))}
        </div>
      </div>
    </>
  );
}
