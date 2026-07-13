"use client";
import Dashboard from "@/screens/Dashboard";
import type { LogEntry, Stats, Trade } from "@/lib/api";

const stats: Stats = {
  running: true,
  connected: true,
  session: "London",
  balance: "$97,025.28",
  equity: "$97,025.28",
  profit: "$53.00",
  open_trades: "0",
  daily_cap_used: "0",
  next_refresh: "--",
  market_open: false,
};

const log: LogEntry[] = [
  { t: "23:15:35", tag: "MT5", k: "inf", x: "Connected · AtlasFunded-Server", speaker: "Boss" },
  { t: "23:11:37", tag: "MT5", k: "inf", x: "Connected · AtlasFunded-Server", speaker: "Boss" },
];

const trades: Trade[] = [
  { id: "1", date: "Jul 10", side: "BUY", lots: "0.10", entry: "52,300.00", exit: "52,410.00", pips: "+110", pnl: 110, win: true, pnl_text: "+$110.00" },
  { id: "2", date: "Jul 09", side: "SELL", lots: "0.10", entry: "52,600.00", exit: "52,540.00", pips: "+60", pnl: 60, win: true, pnl_text: "+$60.00" },
  { id: "3", date: "Jul 08", side: "BUY", lots: "0.10", entry: "52,100.00", exit: "52,040.00", pips: "-60", pnl: -60, win: false, pnl_text: "-$60.00" },
];

export default function DebugDashboardPage() {
  return (
    <div className="full-viewport">
      <Dashboard
        running={true}
        log={log}
        stats={stats}
        trades={trades}
        calendarEvents={[]}
        marketReadings={[
          { label: "US30", price: "52,687.00", change_pct: 0.67 },
          { label: "GOLD", price: "4,709.00", change_pct: -0.13 },
        ]}
        onOpenSettings={() => {}}
        onDisconnect={() => {}}
        onStartBot={async () => {}}
        onStopBot={async () => {}}
      />
    </div>
  );
}
