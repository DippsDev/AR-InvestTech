import { getConnection } from "./connection";
import type { CalendarEvent } from "./dashboardData";

// Every call reads the connection fresh (never cached at module scope) and
// attaches the API token header if one is set (the backend doesn't currently
// enforce it, but sending it is harmless and future-proofs against it doing so).
async function req(path: string, init?: RequestInit): Promise<Response> {
  const { baseUrl, token } = getConnection();
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (token) headers["X-API-Token"] = token;
  if (init?.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  let r: Response;
  try {
    r = await fetch(`${baseUrl}${path}`, { ...init, headers });
  } catch {
    // fetch only throws on a network-level failure (DNS, dead tunnel,
    // CORS block) — surface that distinctly from an HTTP error response.
    throw new Error(`Backend not reachable at ${baseUrl || "(no URL set)"} — check the Backend URL in Settings.`);
  }
  if (!r.ok) {
    throw new Error(`Backend returned ${r.status} for ${path}.`);
  }
  return r;
}

export interface OpenPosition {
  ticket: number;
  symbol: string;
  side: "BUY" | "SELL";
  entry: string;
  sl: string;
  tp: string;
  lots: string;
  float_pnl: string;
  breakeven: boolean;
}

export interface ActiveSymbol {
  symbol: string;
  strategy: "SB" | "TL";
  price: string | null;
  market_open: boolean;
}

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
  // Every currently-open position across all 6 concurrent SB/TL instances
  // (not just one) — see multi_symbol_targets.py on the backend.
  open_positions?: OpenPosition[];
  // One entry per (strategy, symbol) instance the bot is configured to
  // trade — replaces the old single symbol/price fields now that Silver
  // Bullet and Trendline each run across their own top-3 symbols.
  active_symbols?: ActiveSymbol[];
  // Extras surfaced from backend config so the UI never lies about settings.
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
  speaker: string;
}

export interface Trade {
  id: string;
  date: string;
  symbol?: string;
  side: "BUY" | "SELL";
  lots: string;
  entry: string;
  exit: string;
  pips: string;
  pnl: number;
  win: boolean;
  pnl_text?: string;
}

export interface MarketReading {
  label: string;
  price: string | null;
  change_pct: number | null;
}

export interface Settings {
  login: string;
  server: string;
  risk_pct: string;
  daily_loss_limit_usd: string;
  max_trades_per_day: string;
  max_drawdown_pct: string;
  aggressive: boolean;
  off_hours:  boolean;
  news:       boolean;
  // Write-only: never populated from the backend. Blank means "don't change".
  password?: string;
  // Read-only: trading symbols come from the backend's multi_symbol_targets
  // config (top-3 per strategy by backtested profit factor), not a
  // user-editable field — never sent back on save.
  sb_symbols?: string[];
  tl_symbols?: string[];
}

export const apiClient = {
  async checkLicense() {
    try {
      const r = await req("/license");
      return r.json();
    } catch {
      return { ok: false };
    }
  },
  async validateLicense(key: string) {
    // No backend configured yet: validate locally against the build-time env key.
    if (!getConnection().baseUrl) {
      await new Promise(r => setTimeout(r, 800));
      const expected = process.env.NEXT_PUBLIC_LICENSE_KEY;
      if (!expected || key !== expected) return { ok: false, error: "Invalid license key." };
      return { ok: true };
    }
    try {
      const r = await req("/license/validate", {
        method: "POST",
        body: JSON.stringify({ key }),
      });
      return r.json();
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : "Backend not reachable. Check the backend URL in Settings." };
    }
  },
  async validateActivation(key: string) {
    // Deprecated: single-license flow only. Kept for backwards compatibility.
    await new Promise(r => setTimeout(r, 200));
    return { ok: true };
  },

  async connectMt5(): Promise<{ ok: boolean; server?: string; login?: string; balance?: string; error?: string }> {
    try {
      const r = await req("/mt5/connect", { method: "POST" });
      return r.json();
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : "Backend not reachable. Check the backend URL in Settings." };
    }
  },

  async startBot(): Promise<{ running: boolean }> {
    const r = await req("/bot/start", { method: "POST" });
    return r.json();
  },

  async stopBot(): Promise<{ running: boolean }> {
    const r = await req("/bot/stop", { method: "POST" });
    return r.json();
  },

  async restartBot(): Promise<{ running: boolean }> {
    const r = await req("/bot/restart", { method: "POST" });
    return r.json();
  },

  async getStats(): Promise<Stats> {
    const r = await req("/stats");
    return r.json();
  },

  async getLog(): Promise<LogEntry[]> {
    const r = await req("/log");
    return r.json();
  },

  async getTrades(): Promise<Trade[]> {
    const r = await req("/trades");
    return r.json();
  },

  async getCalendar(): Promise<CalendarEvent[]> {
    try {
      const r = await req("/calendar");
      if (!r.ok) return [];
      return r.json();
    } catch {
      return [];
    }
  },

  async getMarket(): Promise<MarketReading[]> {
    try {
      const r = await req("/market");
      if (!r.ok) return [];
      return r.json();
    } catch {
      return [];
    }
  },

  async getSettings(): Promise<Settings> {
    const r = await req("/settings");
    return r.json();
  },

  async saveSettings(data: Settings): Promise<{ ok: boolean }> {
    const r = await req("/settings", {
      method: "POST",
      body: JSON.stringify(data),
    });
    return r.json();
  },
};
