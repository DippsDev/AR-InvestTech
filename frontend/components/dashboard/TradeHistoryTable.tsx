"use client";
import { useMemo, useState } from "react";
import type { Trade } from "@/lib/api";

interface Props {
  trades: Trade[];
}

interface TradeGroup {
  key: string;
  symbol: string;
  side: Trade["side"];
  trades: Trade[];
  totalPnl: number;
  wins: number;
  losses: number;
}

const COLS = ["Date", "Symbol", "Side", "Lots", "Entry", "Exit", "Pips", "P/L"];

function parseLots(value: string): number {
  const n = Number(value.replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function formatMoney(n: number): string {
  const sign = n >= 0 ? "+" : "-";
  return `${sign}$${Math.abs(n).toFixed(2)}`;
}

function formatLots(n: number): string {
  return (Math.round(n * 100) / 100).toFixed(2);
}

function groupTrades(trades: Trade[]): TradeGroup[] {
  const map = new Map<string, TradeGroup>();
  for (const trade of trades) {
    const symbol = trade.symbol ?? "—";
    const key = `${symbol}|${trade.side}`;
    let group = map.get(key);
    if (!group) {
      group = {
        key,
        symbol,
        side: trade.side,
        trades: [],
        totalPnl: 0,
        wins: 0,
        losses: 0,
      };
      map.set(key, group);
    }
    group.trades.push(trade);
    group.totalPnl += trade.pnl;
    if (trade.win) group.wins += 1;
    else group.losses += 1;
  }
  return Array.from(map.values()).sort((a, b) => {
    if (b.trades.length !== a.trades.length) return b.trades.length - a.trades.length;
    return a.symbol.localeCompare(b.symbol);
  });
}

function TradeCard({ trade }: { trade: Trade }) {
  return (
    <div
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderLeft: `3px solid ${trade.win ? "#22C55E" : "#EF4444"}`,
        borderRadius: 6,
        padding: "8px 10px",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
        <span style={{ fontSize: 11, color: "var(--dash-text-dim)" }}>{trade.date}</span>
        <span style={{ fontSize: 13, fontWeight: 700, color: trade.win ? "#22C55E" : "#EF4444" }}>
          {trade.pnl_text ?? formatMoney(trade.pnl)}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginTop: 6,
          paddingTop: 6,
          borderTop: "1px solid var(--dash-border)",
          fontSize: 11,
          color: "var(--dash-text-sub)",
          flexWrap: "wrap",
        }}
      >
        <span>{trade.lots} lots</span>
        <span>
          {trade.entry} → {trade.exit}
        </span>
        <span style={{ marginLeft: "auto", color: trade.win ? "#22C55E" : "#EF4444" }}>{trade.pips} pips</span>
      </div>
    </div>
  );
}

function HistoryGroup({
  group,
  expanded,
  onToggle,
}: {
  group: TradeGroup;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isUp = group.totalPnl >= 0;
  const totalLots = group.trades.reduce((sum, t) => sum + parseLots(t.lots), 0);
  const isSingle = group.trades.length === 1;

  if (isSingle) {
    const trade = group.trades[0];
    return (
      <div
        className="history-group-card"
        style={{ borderLeft: `3px solid ${trade.win ? "#22C55E" : "#EF4444"}` }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, flexWrap: "wrap" }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: trade.side === "BUY" ? "#22C55E" : "#EF4444" }}>
              {trade.side}
            </span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--dash-text)" }}>{group.symbol}</span>
            <span style={{ fontSize: 11, color: "var(--dash-text-dim)" }}>{trade.date}</span>
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: trade.win ? "#22C55E" : "#EF4444", flexShrink: 0 }}>
            {trade.pnl_text ?? formatMoney(trade.pnl)}
          </span>
        </div>
        <div className="history-group-meta">
          <span>{trade.lots} lots</span>
          <span>
            {trade.entry} → {trade.exit}
          </span>
          <span style={{ marginLeft: "auto", color: trade.win ? "#22C55E" : "#EF4444" }}>{trade.pips} pips</span>
        </div>
      </div>
    );
  }

  return (
    <div
      className="history-group-card"
      style={{ borderLeft: `3px solid ${isUp ? "#22C55E" : "#EF4444"}` }}
    >
      <button
        type="button"
        className="history-group-hit"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 0, flexWrap: "wrap" }}>
            <span
              className="history-group-chevron"
              style={{ transform: expanded ? "rotate(90deg)" : "none" }}
              aria-hidden
            >
              ›
            </span>
            <span style={{ fontSize: 11, fontWeight: 700, color: group.side === "BUY" ? "#22C55E" : "#EF4444" }}>
              {group.side}
            </span>
            <span style={{ fontSize: 12, fontWeight: 700, color: "var(--dash-text)" }}>{group.symbol}</span>
            <span className="history-group-count">{group.trades.length}</span>
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: isUp ? "#22C55E" : "#EF4444", flexShrink: 0 }}>
            {formatMoney(group.totalPnl)}
          </span>
        </div>
        <div className="history-group-meta">
          <span>{formatLots(totalLots)} lots</span>
          <span>
            {group.wins}W / {group.losses}L
          </span>
        </div>
      </button>

      {expanded && (
        <div className="history-group-legs">
          {group.trades.map(trade => (
            <TradeCard key={trade.id} trade={trade} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TradeHistoryTable({ trades }: Props) {
  const groups = useMemo(() => groupTrades(trades), [trades]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const toggle = (key: string) => {
    setExpanded(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div
      className="dash-card"
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 12,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        flex: 1,
        minHeight: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#F97316" }} />
          <span style={{ fontSize: 10, fontWeight: 800, color: "#F97316", letterSpacing: ".06em" }}>
            TRADE HISTORY · LAST 30 DAYS
          </span>
        </div>
        {trades.length > 0 && (
          <span className="history-group-summary" style={{ fontSize: 10, fontWeight: 600, color: "var(--dash-text-muted)" }}>
            {trades.length} trades
            {groups.length < trades.length ? ` · ${groups.length} groups` : ""}
          </span>
        )}
      </div>

      <div className="dark-scroll" style={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "auto" }}>
        {trades.length === 0 ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", flex: 1, minHeight: 120 }}>
            <span style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>No closed trades in the last 30 days.</span>
          </div>
        ) : (
          <>
            {/* Mobile: group by symbol + side so phones don't scroll a long
                flat list of every closed leg. Expand a group to see fills. */}
            <div className="trade-cards">
              {groups.map(group => (
                <HistoryGroup
                  key={group.key}
                  group={group}
                  expanded={Boolean(expanded[group.key])}
                  onToggle={() => toggle(group.key)}
                />
              ))}
            </div>

            {/* Desktop table stays ungrouped — a scrollable grid handles
                density better than collapsible cards on wide screens. */}
            <div className="tbl-wrap">
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                <thead>
                  <tr>
                    {COLS.map(c => (
                      <th
                        key={c}
                        style={{
                          textAlign: c === "Date" || c === "Symbol" || c === "Side" ? "left" : "right",
                          padding: "4px 8px",
                          fontSize: 10,
                          fontWeight: 700,
                          color: "var(--dash-text-muted)",
                          letterSpacing: ".04em",
                          borderBottom: "1px solid var(--dash-border)",
                        }}
                      >
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.map(t => (
                    <tr key={t.id} style={{ borderLeft: `3px solid ${t.win ? "#22C55E" : "#EF4444"}` }}>
                      <td style={{ padding: "6px 8px", color: "var(--dash-text)" }}>{t.date}</td>
                      <td style={{ padding: "6px 8px", color: "var(--dash-text)", fontWeight: 600 }}>{t.symbol ?? "—"}</td>
                      <td style={{ padding: "6px 8px", color: t.side === "BUY" ? "#22C55E" : "#EF4444", fontWeight: 700 }}>
                        {t.side}
                      </td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.lots}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.entry}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.exit}</td>
                      <td style={{ padding: "6px 8px", textAlign: "right", color: "var(--dash-text-sub)" }}>{t.pips}</td>
                      <td
                        style={{
                          padding: "6px 8px",
                          textAlign: "right",
                          fontWeight: 700,
                          color: t.win ? "#22C55E" : "#EF4444",
                        }}
                      >
                        {t.pnl_text ?? t.pnl}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
