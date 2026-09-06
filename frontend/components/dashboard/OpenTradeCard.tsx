"use client";
import type { OpenPosition, Stats } from "@/lib/api";

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

function PositionBlock({ trade }: { trade: OpenPosition }) {
  const isUp = trade.float_pnl.startsWith("+");
  return (
    <div className="open-trade-tile">
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
          <span style={{ fontSize: 18, fontWeight: 800, color: "var(--dash-text)", overflow: "hidden", textOverflow: "ellipsis" }}>{trade.symbol}</span>
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              color: trade.side === "BUY" ? "#111827" : "#F3F4F6",
              background: trade.side === "BUY" ? "#22C55E" : "#EF4444",
              padding: "2px 6px",
              borderRadius: 4,
              flexShrink: 0,
            }}
          >
            {trade.side}
          </span>
        </div>
        <span style={{ fontSize: 13, fontWeight: 700, color: isUp ? "#22C55E" : "#EF4444", flexShrink: 0 }}>
          {trade.float_pnl}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <Row label="Entry" value={trade.entry} />
        <Row label="Stop Loss" value={trade.sl} />
        <Row label="Take Profit" value={trade.tp} />
        <Row label="Lots" value={trade.lots} />
        <Row label="Breakeven" value={trade.breakeven ? "Yes" : "No"} />
      </div>
    </div>
  );
}

export default function OpenTradeCard({ stats }: Props) {
  const trades = stats?.open_positions ?? [];

  return (
    <div
      className={`dash-card${trades.length > 0 ? " open-trades-card--populated" : ""}`}
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        overflowY: "auto",
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".08em" }}>
          OPEN TRADES
        </span>
        {trades.length > 0 && (
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)" }}>
            {trades.length}
          </span>
        )}
      </div>

      {trades.length > 0 ? (
        <div className="open-trades-grid">
          {trades.map(trade => (
            <PositionBlock key={trade.ticket} trade={trade} />
          ))}
        </div>
      ) : (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", minHeight: 80 }}>
          <span style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>No open positions</span>
        </div>
      )}
    </div>
  );
}
