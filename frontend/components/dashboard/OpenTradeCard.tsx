"use client";
import { useMemo, useState, type ReactNode } from "react";
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
        fontWeight: 800,
        color: side === "BUY" ? "#052E16" : "#F3F4F6",
        background: side === "BUY" ? "#22C55E" : "#EF4444",
        padding: "2px 6px",
        borderRadius: 4,
        letterSpacing: ".04em",
        flexShrink: 0,
      }}
    >
      {side}
    </span>
  );
}

function Meta({ children }: { children: ReactNode }) {
  return (
    <span style={{ fontSize: 11, color: "var(--dash-text-muted)", whiteSpace: "nowrap" }}>
      {children}
    </span>
  );
}

function LegRow({ trade }: { trade: OpenPosition }) {
  const isUp = trade.float_pnl.startsWith("+") || parseMoney(trade.float_pnl) >= 0;
  return (
    <div className="open-trade-leg">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-dim)" }}>#{trade.ticket}</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: isUp ? "var(--dash-up)" : "var(--dash-down)", flexShrink: 0 }}>
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

function PositionTile({
  group,
  expanded,
  onToggle,
  share,
}: {
  group: TradeGroup;
  expanded: boolean;
  onToggle: () => void;
  share: number;
}) {
  const isUp = group.totalPnl >= 0;
  const isGroup = group.trades.length > 1;
  const trade = group.trades[0];
  const beCount = group.trades.filter(t => t.breakeven).length;
  const avgEntry =
    group.trades.reduce((sum, t) => sum + parseMoney(t.entry), 0) / group.trades.length;
  const accent = group.side === "BUY" ? "var(--dash-up)" : "var(--dash-down)";
  const pnlColor = isUp ? "var(--dash-up)" : "var(--dash-down)";

  return (
    <div
      className="open-trade-tile"
      style={{
        borderLeft: `3px solid ${accent}`,
        background: `linear-gradient(180deg, ${isUp ? "rgba(34,197,94,0.08)" : "rgba(239,68,68,0.08)"} 0%, var(--dash-card-bg-2) 48%)`,
      }}
    >
      {isGroup ? (
        <button
          type="button"
          className="open-trade-tile-hit"
          onClick={onToggle}
          aria-expanded={expanded}
        >
          <TileHeader
            symbol={group.symbol}
            side={group.side}
            count={group.trades.length}
            pnl={formatMoney(group.totalPnl)}
            pnlColor={pnlColor}
            expanded={expanded}
            chevron
          />
          <TileStats
            lots={formatLots(group.totalLots)}
            entry={avgEntry.toLocaleString(undefined, {
              minimumFractionDigits: 2,
              maximumFractionDigits: 5,
            })}
            be={beCount > 0 ? `${beCount}/${group.trades.length}` : undefined}
            share={share}
            hint={expanded ? "Tap to hide legs" : `Tap to view ${group.trades.length} legs`}
          />
        </button>
      ) : (
        <>
          <TileHeader
            symbol={group.symbol}
            side={group.side}
            pnl={trade.float_pnl}
            pnlColor={pnlColor}
          />
          <TileStats
            lots={trade.lots}
            entry={trade.entry}
            sl={trade.sl}
            tp={trade.tp}
            be={trade.breakeven ? "Yes" : undefined}
            share={share}
          />
        </>
      )}

      {isGroup && expanded && (
        <div className="open-trade-legs dark-scroll">
          {group.trades.map(t => (
            <LegRow key={t.ticket} trade={t} />
          ))}
        </div>
      )}
    </div>
  );
}

function TileHeader({
  symbol,
  side,
  count,
  pnl,
  pnlColor,
  expanded,
  chevron,
}: {
  symbol: string;
  side: OpenPosition["side"];
  count?: number;
  pnl: string;
  pnlColor: string;
  expanded?: boolean;
  chevron?: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
          {chevron && (
            <span
              style={{
                fontSize: 12,
                color: "var(--dash-text-dim)",
                transform: expanded ? "rotate(90deg)" : "none",
                transition: "transform .15s ease",
                display: "inline-block",
                flexShrink: 0,
                lineHeight: 1,
              }}
              aria-hidden
            >
              ›
            </span>
          )}
          <span
            style={{
              fontSize: 16,
              fontWeight: 800,
              color: "var(--dash-text)",
              letterSpacing: "-0.01em",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {symbol}
          </span>
          <SideBadge side={side} />
          {count != null && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 800,
                color: "var(--dash-text-sub)",
                background: "var(--dash-card-bg)",
                border: "1px solid var(--dash-border)",
                padding: "2px 7px",
                borderRadius: 999,
                flexShrink: 0,
              }}
            >
              {count}
            </span>
          )}
        </div>
      </div>
      <span style={{ fontSize: 18, fontWeight: 800, color: pnlColor, flexShrink: 0, letterSpacing: "-0.02em" }}>
        {pnl}
      </span>
    </div>
  );
}

function TileStats({
  lots,
  entry,
  sl,
  tp,
  be,
  share,
  hint,
}: {
  lots: string;
  entry: string;
  sl?: string;
  tp?: string;
  be?: string;
  share: number;
  hint?: string;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "6px 14px",
          paddingTop: 2,
        }}
      >
        <Meta>
          <strong style={{ color: "var(--dash-text)", fontWeight: 700 }}>{lots}</strong> lots
        </Meta>
        <Meta>
          @ <strong style={{ color: "var(--dash-text)", fontWeight: 700 }}>{entry}</strong>
        </Meta>
        {sl && (
          <Meta>
            SL <strong style={{ color: "var(--dash-text)", fontWeight: 600 }}>{sl}</strong>
          </Meta>
        )}
        {tp && (
          <Meta>
            TP <strong style={{ color: "var(--dash-text)", fontWeight: 600 }}>{tp}</strong>
          </Meta>
        )}
        {be && (
          <Meta>
            BE <strong style={{ color: "var(--dash-accent-yellow)", fontWeight: 700 }}>{be}</strong>
          </Meta>
        )}
      </div>
      <div
        style={{
          height: 3,
          borderRadius: 999,
          background: "var(--dash-border)",
          overflow: "hidden",
        }}
        title={`${Math.round(share * 100)}% of open exposure`}
      >
        <div
          style={{
            width: `${Math.max(6, Math.round(share * 100))}%`,
            height: "100%",
            borderRadius: 999,
            background: "var(--dash-text-muted)",
            opacity: 0.85,
          }}
        />
      </div>
      {hint && (
        <span style={{ fontSize: 10, fontWeight: 600, color: "var(--dash-text-dim)", letterSpacing: ".02em" }}>
          {hint}
        </span>
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
  const totalLots = useMemo(
    () => groups.reduce((sum, g) => sum + g.totalLots, 0),
    [groups],
  );
  const exposure = useMemo(
    () => groups.reduce((sum, g) => sum + Math.abs(g.totalPnl), 0) || 1,
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
      className={`dash-card${trades.length > 0 ? " open-trades-card--populated" : ""}`}
      style={{
        background: "var(--dash-card-bg)",
        border: "1px solid var(--dash-border)",
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        minWidth: 0,
        minHeight: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--dash-text-muted)", letterSpacing: ".08em" }}>
            OPEN TRADES
          </span>
          {trades.length > 0 ? (
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
              <span
                style={{
                  fontSize: 26,
                  fontWeight: 800,
                  color: netUp ? "var(--dash-up)" : "var(--dash-down)",
                  letterSpacing: "-0.02em",
                  lineHeight: 1,
                }}
              >
                {formatMoney(netPnl)}
              </span>
              <span style={{ fontSize: 12, color: "var(--dash-text-muted)" }}>
                floating · {formatLots(totalLots)} lots · {trades.length} legs
                {groups.length < trades.length ? ` · ${groups.length} groups` : ""}
              </span>
            </div>
          ) : (
            <span style={{ fontSize: 13, color: "var(--dash-text-dim)" }}>No open positions</span>
          )}
        </div>
      </div>

      {trades.length > 0 && (
        <div className="open-trades-grid">
          {groups.map(group => (
            <PositionTile
              key={group.key}
              group={group}
              expanded={isExpanded(group)}
              onToggle={() => toggle(group.key)}
              share={Math.abs(group.totalPnl) / exposure}
            />
          ))}
        </div>
      )}
    </div>
  );
}
