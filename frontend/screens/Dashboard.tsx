"use client";
import type { LogEntry, MarketReading, Stats, Trade } from "@/lib/api";
import TickerBar from "@/components/dashboard/TickerBar";
import TopStoryCard from "@/components/dashboard/TopStoryCard";
import BookCard from "@/components/dashboard/BookCard";
import OpenTradeCard from "@/components/dashboard/OpenTradeCard";
import TradeHistoryTable from "@/components/dashboard/TradeHistoryTable";
import EventCalendar from "@/components/dashboard/EventCalendar";
import BotLog from "@/components/dashboard/BotLog";
import PersonaCard from "@/components/dashboard/PersonaCard";
import MarketHeatmap from "@/components/dashboard/MarketHeatmap";
import { PERSONAS, PERSONA_ORDER } from "@/lib/personas";
import type { Book, CalendarEvent } from "@/lib/dashboardData";

interface Props {
  running: boolean;
  log: LogEntry[];
  stats: Stats | null;
  trades: Trade[];
  calendarEvents: CalendarEvent[];
  marketReadings: MarketReading[];
  onOpenSettings: () => void;
  onDisconnect: () => void;
  onStartBot: () => Promise<void>;
  onStopBot: () => Promise<void>;
}

function parseMoney(s?: string | null): number {
  if (!s) return 0;
  const n = parseFloat(s.replace(/[^0-9.-]/g, ""));
  return Number.isFinite(n) ? n : 0;
}

function latestNote(log: LogEntry[], speaker: string, idle: string): { text: string; time?: string } {
  const entry = log.find(e => e.speaker === speaker);
  return entry ? { text: entry.x, time: entry.t } : { text: idle, time: undefined };
}

export default function Dashboard(props: Props) {
  const { stats, log, trades } = props;
  const balance = parseMoney(stats?.balance);
  const equity = parseMoney(stats?.equity);
  const profit = parseMoney(stats?.profit);

  const accountBook: Book = {
    label: "ACCOUNT",
    cash: balance,
    value: equity,
    todayChange: profit,
    todayChangePct: balance ? (profit / balance) * 100 : 0,
    data: [],
    color: profit >= 0 ? "#22C55E" : "#EF4444",
  };

  // Must match backend's `strftime("%b %d")` exactly (zero-padded day) so
  // today's trades actually match on the 1st-9th of the month.
  const today = new Date().toLocaleDateString("en-US", { month: "short", day: "2-digit" });
  const todaysTrades = trades.filter(t => t.date === today);
  const wins = trades.filter(t => t.win).length;
  const losses = trades.filter(t => !t.win).length;
  // Realized P&L across the closed-trade history get_trades() returns
  // (bot-magic deals over the last 30 days) — not the account's floating
  // profit, which is open positions and already shown on the book card.
  const realizedPnl = trades.reduce((sum, t) => sum + t.pnl, 0);
  const realizedPnlText = realizedPnl >= 0
    ? `+$${realizedPnl.toFixed(2)}`
    : `-$${Math.abs(realizedPnl).toFixed(2)}`;
  const maxTrades = stats?.max_trades ? parseInt(stats.max_trades, 10) : undefined;
  const newsPaused = Boolean(stats?.session?.includes("News pause"));

  const personaData: Record<string, { badge?: { text: string; color: string } | { text: string; color: string }[] }> = {
    Boss: {
      badge: { text: stats?.running ? "LIVE" : "PAUSED", color: stats?.running ? "#22C55E" : "#6B7280" },
    },
    Trader: {
      badge: (() => {
        const open = stats?.open_positions ?? [];
        if (open.length === 0) return { text: "NO OPEN TRADES", color: "#6B7280" };
        if (open.length === 1) {
          return { text: `${open[0].side} OPEN`, color: open[0].side === "BUY" ? "#22C55E" : "#EF4444" };
        }
        return { text: `${open.length} OPEN`, color: "#3B82F6" };
      })(),
    },
    Risk: {
      badge: {
        text: maxTrades != null ? `${todaysTrades.length}/${maxTrades} TODAY` : `${todaysTrades.length} TODAY`,
        color: maxTrades != null && todaysTrades.length >= maxTrades ? "#EF4444" : "#F97316",
      },
    },
    "News Guard": {
      badge: { text: newsPaused ? "NEWS PAUSE" : "CLEAR", color: newsPaused ? "#EF4444" : "#22C55E" },
    },
    Grader: {
      badge: [
        { text: realizedPnlText, color: realizedPnl >= 0 ? "#22C55E" : "#EF4444" },
        { text: `${wins}W / ${losses}L`, color: "#8B5CF6" },
      ],
    },
    Scanner: {
      badge: { text: stats?.session ?? "--", color: "#3B82F6" },
    },
  };

  return (
    <div
      className="dashboard-root"
      style={{
        display: "flex",
        flexDirection: "column",
        background: "var(--dash-bg)",
        color: "var(--dash-text)",
      }}
    >
      <TickerBar
        running={props.running}
        stats={stats}
        onOpenSettings={props.onOpenSettings}
        onDisconnect={props.onDisconnect}
        onStartBot={props.onStartBot}
        onStopBot={props.onStopBot}
      />

      <div
        className="dash-body"
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          overflow: "hidden",
        }}
      >
        {/* Main content column */}
        <div
          className="dash-main-col"
          style={{
            flex: 1,
            minWidth: 0,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            padding: 14,
            gap: 14,
          }}
        >
          {/* Scrollable content area */}
          <div
            className="dash-scroll-area dark-scroll"
            style={{
              flex: 1,
              minHeight: 0,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: 14,
            }}
          >
            {/* Top row: bot status + account + open trade */}
            <div className="dash-top-row">
              <TopStoryCard stats={stats} />
              <BookCard book={accountBook} />
              <OpenTradeCard stats={stats} />
            </div>

            {/* The office — one card per persona, always visible. Flexbox
                (not grid) on purpose: grid's auto-fit tracks can't express
                "give the heatmap all the leftover width on whatever line it
                lands on" without knowing the column count in advance. Flex
                items sharing a wrapped line distribute growth among
                themselves automatically, whatever that count turns out to be. */}
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 10,
              }}
            >
              {PERSONA_ORDER.map(name => {
                const persona = PERSONAS[name];
                const note = latestNote(log, name, persona.idleNote);
                return (
                  <div key={name} style={{ flex: "1 1 200px", minWidth: 0 }}>
                    <PersonaCard
                      persona={persona}
                      badge={personaData[name]?.badge}
                      note={note.text}
                      time={note.time}
                      active={props.running}
                    />
                  </div>
                );
              })}
              {/* Grows to absorb whatever's left on its line — a full row to
                  itself if the personas above filled evenly, or the tail end
                  of the last persona row otherwise. Stretches (row default)
                  to match the taller persona cards; MarketHeatmap fills that
                  stretched height itself so the tiles reach all the way down
                  instead of leaving bare background below them. */}
              <div className="dash-heatmap-wrap" style={{ flex: "3 1 320px", minWidth: 0, display: "flex" }}>
                <MarketHeatmap readings={props.marketReadings} />
              </div>
            </div>

            {/* Trade history. display:flex here (not just on the card inside)
                so the card can fill this wrapper via flex:1 instead of
                height:100% — on mobile .dash-scroll-area's ancestors switch
                to auto/visible so page scroll is unbroken (see dash-body
                comment below), which leaves height:100% with no definite
                reference to resolve against and the card collapses to its
                content, stranding blank space up to this wrapper's
                minHeight. flex:1/minHeight:0 sidesteps that entirely. */}
            <div style={{ flex: 1, minHeight: 320, display: "flex", flexDirection: "column" }}>
              <TradeHistoryTable trades={props.trades} />
            </div>
          </div>

          {/* Event calendar — fixed at bottom of main column */}
          <EventCalendar events={props.calendarEvents} />
        </div>

        {/* Bot activity column. display:flex + BotLog's flex:1/minHeight:0
            (instead of height:100%) lets a mobile max-height cap on this
            box actually work: a percentage height on a child only resolves
            against an ancestor with a *definite* height, and max-height
            alone never makes an auto-height box definite — but the flex
            layout algorithm is explicitly defined to handle a max-height-
            constrained flex container correctly, shrinking to content below
            the cap and clamping (with the child sharing the difference)
            above it. */}
        <div
          className="dash-chat-col"
          style={{
            width: 360,
            flexShrink: 0,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            padding: "14px 14px 14px 0",
          }}
        >
          <BotLog log={props.log} running={props.running} />
        </div>
      </div>
    </div>
  );
}
