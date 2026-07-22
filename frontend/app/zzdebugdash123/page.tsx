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
  open_trades: "2",
  daily_cap_used: "0",
  next_refresh: "--",
  market_open: true,
  open_positions: [
    { ticket: 1001, symbol: "DE30m", side: "BUY", entry: "25,152.00", sl: "25,100.00", tp: "25,300.00", lots: "0.05", float_pnl: "+$12.40", breakeven: false },
    { ticket: 1002, symbol: "EURUSDm", side: "SELL", entry: "1.14095", sl: "1.14200", tp: "1.13850", lots: "0.10", float_pnl: "-$4.20", breakeven: false },
  ],
  active_symbols: [
    { symbol: "DE30m", strategy: "SB", price: "25,152.00", market_open: true },
    { symbol: "EURUSDm", strategy: "SB", price: "1.14095", market_open: true },
    { symbol: "GBPUSDm", strategy: "SB", price: "1.33715", market_open: true },
    { symbol: "DE30m", strategy: "TL", price: "25,152.00", market_open: true },
    { symbol: "USDJPYm", strategy: "TL", price: "163.123", market_open: true },
    { symbol: "USTECm", strategy: "TL", price: "29,088.24", market_open: true },
  ],
};

const log: LogEntry[] = [
  { t: "23:15:35", tag: "MT5", k: "inf", x: "Connected · AtlasFunded-Server", speaker: "Boss" },
  { t: "23:11:37", tag: "MT5", k: "inf", x: "Connected · AtlasFunded-Server", speaker: "Boss" },
];

const trades: Trade[] = [
  { id: "1", date: "Jul 10", symbol: "DE30m", side: "BUY", lots: "0.10", entry: "25,100.00", exit: "25,210.00", pips: "+110", pnl: 110, win: true, pnl_text: "+$110.00" },
  { id: "2", date: "Jul 09", symbol: "USDJPYm", side: "SELL", lots: "0.10", entry: "163.400", exit: "163.340", pips: "+60", pnl: 60, win: true, pnl_text: "+$60.00" },
  { id: "3", date: "Jul 08", symbol: "GBPUSDm", side: "BUY", lots: "0.10", entry: "1.33800", exit: "1.33740", pips: "-60", pnl: -60, win: false, pnl_text: "-$60.00" },
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
          { label: "DE30m", price: "25,152.00", change_pct: 0.67 },
          { label: "EURUSDm", price: "1.14095", change_pct: -0.13 },
          { label: "GBPUSDm", price: "1.33715", change_pct: 0.22 },
          { label: "USDJPYm", price: "163.123", change_pct: -0.08 },
          { label: "USTECm", price: "29,088.24", change_pct: 1.05 },
        ]}
        onOpenSettings={() => {}}
        onDisconnect={() => {}}
        onStartBot={async () => {}}
        onStopBot={async () => {}}
      />
    </div>
  );
}
