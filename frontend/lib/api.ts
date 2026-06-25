export interface Stats {
  running: boolean;
  connected: boolean;
  session: string;
  balance: string;
  equity: string;
  profit: string;
  profit_pct: string;
  open_trades: string;
  daily_cap_used: string;
  next_refresh: string;
  open_trade?: {
    symbol: string;
    side: "BUY" | "SELL";
    entry: string;
    sl: string;
    tp: string;
    lots: string;
    float_pnl: string;
    breakeven: boolean;
  };
}

export interface LogEntry {
  t: string;
  tag: string;
  k: "win" | "sig" | "inf";
  x: string;
}

export interface Trade {
  id: string;
  date: string;
  side: "BUY" | "SELL";
  lots: string;
  entry: string;
  exit: string;
  pips: string;
  pnl: number;
  win: boolean;
}

export interface Settings {
  login: string;
  server: string;
  risk_pct: string;
  daily_cap: string;
  max_trades: string;
  trail: boolean;
  bias: boolean;
  news: boolean;
}

export const INITIAL_LOG: LogEntry[] = [
  { t: "09:41:02", tag: "[SIGNAL]", k: "sig", x: "AI confirms BULLISH bias on US30 M5" },
  { t: "09:41:03", tag: "[ENTRY]",  k: "win", x: "BUY 0.08 @ 42,318.4 · SL 42,288.4 · TP 42,368.4" },
  { t: "09:43:18", tag: "[INFO]",   k: "inf", x: "Stop moved to breakeven (42,318.4)" },
  { t: "09:44:55", tag: "[INFO]",   k: "inf", x: "US30 trailing stop active · +18 pts floating" },
];

export const ALL_TRADES: Trade[] = [
  { id: "#10428", date: "Jun 23", side: "BUY",  lots: "0.08", entry: "42,316.1", exit: "42,369.1", pips: "+53", pnl:  42.40, win: true  },
  { id: "#10427", date: "Jun 23", side: "SELL", lots: "0.08", entry: "42,329.8", exit: "42,292.8", pips: "+37", pnl:  29.60, win: true  },
  { id: "#10426", date: "Jun 22", side: "BUY",  lots: "0.06", entry: "42,308.4", exit: "42,283.4", pips: "-25", pnl: -15.00, win: false },
  { id: "#10425", date: "Jun 22", side: "BUY",  lots: "0.08", entry: "42,301.2", exit: "42,365.2", pips: "+64", pnl:  51.20, win: true  },
  { id: "#10424", date: "Jun 21", side: "SELL", lots: "0.08", entry: "42,344.5", exit: "42,370.5", pips: "-26", pnl: -20.80, win: false },
  { id: "#10423", date: "Jun 20", side: "BUY",  lots: "0.10", entry: "42,088.7", exit: "42,154.7", pips: "+66", pnl:  66.00, win: true  },
  { id: "#10422", date: "Jun 20", side: "SELL", lots: "0.08", entry: "42,252.4", exit: "42,209.4", pips: "+43", pnl:  34.40, win: true  },
  { id: "#10421", date: "Jun 19", side: "BUY",  lots: "0.08", entry: "41,971.9", exit: "41,946.9", pips: "-25", pnl: -20.00, win: false },
  { id: "#10420", date: "Jun 19", side: "BUY",  lots: "0.06", entry: "41,965.3", exit: "42,030.3", pips: "+65", pnl:  39.00, win: true  },
  { id: "#10419", date: "Jun 18", side: "SELL", lots: "0.08", entry: "42,190.1", exit: "42,135.1", pips: "+55", pnl:  44.00, win: true  },
];

export const mockApi = {
  async validateLicense(key: string) {
    await new Promise(r => setTimeout(r, 1200));
    const expected = process.env.NEXT_PUBLIC_LICENSE_KEY;
    if (!expected || key !== expected) return { ok: false, error: "Invalid license key." };
    return { ok: true };
  },
  async validateActivation(key: string) {
    await new Promise(r => setTimeout(r, 1200));
    const expected = process.env.NEXT_PUBLIC_ACTIVATION_CODE;
    if (!expected || key !== expected) return { ok: false, error: "Invalid activation code." };
    return { ok: true };
  },
  async connectMt5() {
    return { ok: true, server: "ICMarketsSC-Live07" };
  },
  async getStats(): Promise<Stats> {
    return {
      running: true,
      connected: true,
      session: "London",
      balance: "$4,208.60",
      equity: "$4,237.00",
      profit: "+$84.50",
      profit_pct: "▲ +2.01%",
      open_trades: "1",
      daily_cap_used: "1.01% / 3%",
      next_refresh: "42s",
      open_trade: {
        symbol: "US30",
        side: "BUY",
        entry: "42,318.4",
        sl: "42,288.4",
        tp: "42,368.4",
        lots: "0.08",
        float_pnl: "+$28.40",
        breakeven: true,
      },
    };
  },
  async getTrades(): Promise<Trade[]> { return ALL_TRADES; },
  async getSettings(): Promise<Settings> {
    return { login: "50213394", server: "ICMarketsSC-Live07", risk_pct: "1.0", daily_cap: "3.0", max_trades: "2", trail: true, bias: true, news: false };
  },
  async saveSettings(_data: Settings) { return { ok: true }; },
};
