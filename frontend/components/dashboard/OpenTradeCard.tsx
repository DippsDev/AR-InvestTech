"use client";
import type { Stats } from "@/lib/api";

interface Props {
  stats?: Stats | null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
      <span style={{ color: "var(--dash-text-muted)" }}>{label}</span>
      <span style={{ color: "var(--dash-text)", fontWeight: 600 }}>{value}</span>
    </div>
  );
}

export default function OpenTradeCard({ stats }: Props) {
  const trade = stats?.open_trade;
  const isUp = trade ? trade.float_pnl.startsWith("+") : true;

  return (
    <div
      className="dash-card"
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".08em" }}>
          OPEN TRADE
        </span>
        {trade && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: trade.side === "BUY" ? "#111827" : "#F3F4F6",
              background: trade.side === "BUY" ? "#22C55E" : "#EF4444",
              padding: "2px 8px",
              borderRadius: 4,
            }}
          >
            {trade.side}
          </span>
        )}
      </div>

      {trade ? (
        <>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontSize: 22, fontWeight: 800, color: "var(--dash-text)" }}>{trade.symbol}</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: isUp ? "#22C55E" : "#EF4444" }}>
              {trade.float_pnl}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Row label="Entry" value={trade.entry} />
            <Row label="Stop Loss" value={trade.sl} />
            <Row label="Take Profit" value={trade.tp} />
            <Row label="Lots" value={trade.lots} />
            <Row label="Breakeven" value={trade.breakeven ? "Yes" : "No"} />
          </div>
        </>
      ) : (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", minHeight: 80 }}>
          <span style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>No open position</span>
        </div>
      )}
    </div>
  );
}
