const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface Stats {
  running: boolean;
  connected: boolean;
  session: string;
  balance: string;
  equity: string;
  profit: string;
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
  // Extras surfaced from backend config so the UI never lies about settings.
  symbol?: string;
  risk_pct?: string;
  max_trades?: string;
  timeframe?: string;
  market_open?: boolean;
}

export interface LogEntry {
  t: string;
  tag: string;
  k: "win" | "sig" | "inf" | "warn";
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
  pnl_text?: string;
}

export interface Settings {
  login: string;
  server: string;
  symbol: string;
  risk_pct: string;
  daily_loss_limit_usd: string;
  max_trades_per_day: string;
  max_drawdown_pct: string;
  aggressive: boolean;
  off_hours:  boolean;
}

export const mockApi = {
  async checkLicense() {
    try {
      const r = await fetch(`${BASE}/license`);
      return r.json();
    } catch {
      return { ok: false };
    }
  },
  async validateLicense(key: string) {
    try {
      const r = await fetch(`${BASE}/license/validate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key }),
      });
      return r.json();
    } catch {
      // Fallback to build-time env key if backend is unreachable.
      await new Promise(r => setTimeout(r, 800));
      const expected = process.env.NEXT_PUBLIC_LICENSE_KEY;
      if (!expected || key !== expected) return { ok: false, error: "Invalid license key." };
      return { ok: true };
    }
  },
  async validateActivation(key: string) {
    // Deprecated: single-license flow only. Kept for backwards compatibility.
    await new Promise(r => setTimeout(r, 200));
    return { ok: true };
  },

  async connectMt5(): Promise<{ ok: boolean; server?: string; login?: string; balance?: string; error?: string }> {
    try {
      const r = await fetch(`${BASE}/mt5/connect`, { method: "POST" });
      return r.json();
    } catch {
      return { ok: false, error: "Backend not reachable. Is python server.py running?" };
    }
  },

  async startBot(): Promise<{ running: boolean }> {
    const r = await fetch(`${BASE}/bot/start`, { method: "POST" });
    return r.json();
  },

  async stopBot(): Promise<{ running: boolean }> {
    const r = await fetch(`${BASE}/bot/stop`, { method: "POST" });
    return r.json();
  },

  async getStats(): Promise<Stats> {
    const r = await fetch(`${BASE}/stats`);
    return r.json();
  },

  async getLog(): Promise<LogEntry[]> {
    const r = await fetch(`${BASE}/log`);
    return r.json();
  },

  async getTrades(): Promise<Trade[]> {
    const r = await fetch(`${BASE}/trades`);
    return r.json();
  },

  async getSettings(): Promise<Settings> {
    const r = await fetch(`${BASE}/settings`);
    return r.json();
  },

  async saveSettings(data: Settings): Promise<{ ok: boolean }> {
    const r = await fetch(`${BASE}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    return r.json();
  },
};
