"use client";
import { useMemo, useState } from "react";
import type { OpenPosition, Stats } from "@/lib/api";

interface Props {
  stats?: Stats | null;
}

interface TradeGroup {
  key: string;
  symbol: string;
  side: OpenPosition["side"];
  trades: OpenPosition[];
  totalLots: number;
  totalPnl: number;
}

function parseMoney(value: string): number {
  const n = Number(value.replace(/[^0-9.\-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

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

function groupTrades(trades: OpenPosition[]): TradeGroup[] {
  const map = new Map<string, TradeGroup>();
  for (const trade of trades) {
    const key = `${trade.symbol}|${trade.side}`;
    let group = map.get(key);
    if (!group) {
      group = {
        key,
        symbol: trade.symbol,
        side: trade.side,
        trades: [],
        totalLots: 0,
        totalPnl: 0,
      };
      map.set(key, group);
    }
    group.trades.push(trade);
    group.totalLots += parseLots(trade.lots);
    group.totalPnl += parseMoney(trade.float_pnl);
  }
  return Array.from(map.values()).sort((a, b) => {
    if (b.trades.length !== a.trades.length) return b.trades.length - a.trades.length;
    return a.symbol.localeCompare(b.symbol);
  });
}

function SideBadge({ side }: { side: OpenPosition["side"] }) {
  return (
    <span
      style={{
        fontSize: 9,
        fontWeight: 700,
        color: side === "BUY" ? "#111827" : "#F3F4F6",
        background: side === "BUY" ? "#22C55E" : "#EF4444",
        padding: "2px 6px",
        borderRadius: 4,
        flexShrink: 0,
      }}
    >
      {side}
    </span>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12 }}>
      <span style={{ color: "var(--dash-text-muted)" }}>{label}</span>
      <span style={{ color: "var(--dash-text)", fontWeight: 600 }}>{value}</span>
    </div>
  );
}

function LegRow({ trade }: { trade: OpenPosition }) {
  const isUp = trade.float_pnl.startsWith("+") || parseMoney(trade.float_pnl) >= 0;
  return (
    <div className="open-trade-leg">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-dim)" }}>#{trade.ticket}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: isUp ? "#22C55E" : "#EF4444" }}>
          {trade.float_pnl}
        </span>
      </div>
      <div className="open-trade-leg-meta">
        <span>Entry <strong>{trade.entry}</strong></span>
        <span>SL <strong>{trade.sl}</strong></span>
        <span>TP <strong>{trade.tp}</strong></span>
        <span><strong>{trade.lots}</strong> lots</span>
        {trade.breakeven && <span style={{ color: "var(--dash-accent-yellow)" }}>BE</span>}
      </div>
    </div>
  );
}

function SinglePosition({ trade }: { trade: OpenPosition }) {
  const isUp = trade.float_pnl.startsWith("+") || parseMoney(trade.float_pnl) >= 0;
  return (
    <div className="open-trade-group">
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
          <span className="open-trade-symbol">{trade.symbol}</span>
          <SideBadge side={trade.side} />
        </div>
        <span style={{ fontSize: 13, fontWeight: 700, color: isUp ? "#22C55E" : "#EF4444", flexShrink: 0 }}>
          {trade.float_pnl}
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8 }}>
        <Row label="Entry" value={trade.entry} />
        <Row label="Stop Loss" value={trade.sl} />
        <Row label="Take Profit" value={trade.tp} />
        <Row label="Lots" value={trade.lots} />
        {trade.breakeven && <Row label="Breakeven" value="Yes" />}
      </div>
    </div>
  );
}

function GroupedPosition({
  group,
  expanded,
  onToggle,
}: {
  group: TradeGroup;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isUp = group.totalPnl >= 0;
  const beCount = group.trades.filter(t => t.breakeven).length;
  const avgEntry =
    group.trades.reduce((sum, t) => sum + parseMoney(t.entry), 0) / group.trades.length;

  return (
    <div className="open-trade-group">
      <button
        type="button"
        className="open-trade-group-hit"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, minWidth: 0 }}>
            <span
              className="open-trade-chevron"
              style={{ transform: expanded ? "rotate(90deg)" : "none" }}
              aria-hidden
            >
              ›
            </span>
            <span className="open-trade-symbol">{group.symbol}</span>
            <SideBadge side={group.side} />
            <span className="open-trade-count">{group.trades.length}</span>
          </div>
          <span style={{ fontSize: 13, fontWeight: 700, color: isUp ? "#22C55E" : "#EF4444", flexShrink: 0 }}>
            {formatMoney(group.totalPnl)}
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 8, paddingLeft: 16 }}>
          <Row label="Total lots" value={formatLots(group.totalLots)} />
          <Row
            label="Avg entry"
            value={avgEntry.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 5,
            })}
          />
          {beCount > 0 && <Row label="Breakeven" value={`${beCount}/${group.trades.length}`} />}
        </div>
      </button>

      {expanded && (
        <div className="open-trade-legs dark-scroll">
          {group.trades.map(trade => (
            <LegRow key={trade.ticket} trade={trade} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function OpenTradeCard({ stats }: Props) {
  const trades = stats?.open_positions ?? [];
  const groups = useMemo(() => groupTrades(trades), [trades]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const netPnl = useMemo(
    () => groups.reduce((sum, g) => sum + g.totalPnl, 0),
    [groups],
  );

  const isExpanded = (group: TradeGroup) => {
    if (group.trades.length === 1) return false;
    return expanded[group.key] ?? false;
  };

  const toggle = (key: string) => {
    setExpanded(prev => ({ ...prev, [key]: !(prev[key] ?? false) }));
  };

  const netUp = netPnl >= 0;

  return (
    <div
      className="dash-card open-trades-card"
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        height: "100%",
        minHeight: 0,
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".08em" }}>
          OPEN TRADES
        </span>
        {trades.length > 0 && (
          <span style={{ fontSize: 11, fontWeight: 700, color: netUp ? "#22C55E" : "#EF4444" }}>
            {formatMoney(netPnl)}
            <span style={{ color: "var(--dash-text-muted)", fontWeight: 600 }}>
              {" · "}
              {trades.length}
              {groups.length < trades.length ? ` · ${groups.length} groups` : ""}
            </span>
          </span>
        )}
      </div>

      {trades.length > 0 ? (
        <div className="open-trades-list dark-scroll">
          {groups.map(group =>
            group.trades.length === 1 ? (
              <SinglePosition key={group.key} trade={group.trades[0]} />
            ) : (
              <GroupedPosition
                key={group.key}
                group={group}
                expanded={isExpanded(group)}
                onToggle={() => toggle(group.key)}
              />
            ),
          )}
        </div>
      ) : (
        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", minHeight: 80 }}>
          <span style={{ fontSize: 12, color: "var(--dash-text-dim)" }}>No open positions</span>
        </div>
      )}
    </div>
  );
}
