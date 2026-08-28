# AR-InvestTech

A full-stack multi-strategy algorithmic trading system for MetaTrader 5. It runs **three independent strategies concurrently** — Silver Bullet, Trendline, and Mutanabby — each across its own set of symbols, with per-strategy risk budgets, circuit breakers, and a real-time Next.js monitoring dashboard.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Strategies](#strategies)
  - [Silver Bullet](#silver-bullet-sb)
  - [Trendline](#trendline-tl)
  - [Mutanabby](#mutanabby-mb)
- [Risk Management](#risk-management)
- [Prerequisites](#prerequisites)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Running the System](#running-the-system)
- [API Reference](#api-reference)
- [Frontend Dashboard](#frontend-dashboard)
- [Backtesting](#backtesting)
- [VPS Deployment](#vps-deployment)
- [License Activation](#license-activation)

---

## Overview

| Layer | Technology | Purpose |
|---|---|---|
| Strategy engines | Python + NumPy/Pandas | Signal generation, backtesting (3 strategies) |
| Execution adapters | MetaTrader5 Python SDK | Live order placement and management per symbol |
| Backend API | FastAPI + Uvicorn | REST bridge between bot and frontend |
| Frontend | Next.js 16 + React 19 + Tailwind v4 | Real-time dashboard (monitor, control, trade log) |
| License server | Supabase | Remote license validation |

The bot runs as a background thread managed by the FastAPI server. Each strategy runs one live adapter **per symbol**; all adapters share a per-tick MT5 snapshot cache so a full cycle costs one IPC round-trip per data type instead of one per adapter.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Frontend                             │
│         Next.js 16  ·  React 19  ·  Tailwind CSS v4        │
│                    http://localhost:3000                     │
└───────────────────────────┬─────────────────────────────────┘
                            │  REST  (API_TOKEN auth, CORS allowlist)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Server                          │
│                   server.py  ·  :8000                       │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    BotBridge                         │   │
│  │  bridge.py — license · MT5 connection · bot thread  │   │
│  │  desired-run-state persistence (bot_state.json)     │   │
│  └────────────────────────┬─────────────────────────────┘   │
└───────────────────────────┼─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                   SilverBulletBot (bot.py)                   │
│                                                             │
│  SilverBulletLiveAdapter × SB_TARGETS (DE30m, EURUSDm,      │
│  GBPUSDm, XAUUSDm) — M5, sweep → FVG                        │
│                                                             │
│  TrendlineLiveAdapter × TL_TARGETS (DE30m, USDJPYm,         │
│  USTECm) — H1, trendline touch + candle confirmation        │
│                                                             │
│  MutanabbyLiveAdapter × MB_TARGETS (US30m, JP225m,          │
│  USDJPYm) — H1, SuperTrend flip                             │
│                                                             │
│  All adapters read through src/mt5_cache (one snapshot      │
│  per 5-second loop tick)                                    │
└────────────────────────────┬────────────────────────────────┘
                             │ MetaTrader5 Python SDK
                             ▼
                    ┌────────────────┐
                    │  MT5 Terminal  │
                    └────────────────┘
```

---

## Project Structure

```
ar-investments/
│
├── backend/                    # Python backend (FastAPI + bot + strategies)
│   ├── bot.py                  # Bot entry point — runs all strategies/symbols concurrently
│   ├── bridge.py               # Shared business logic (license, MT5, bot lifecycle, log, run-state)
│   ├── server.py               # FastAPI REST API — run this to serve the frontend
│   ├── config.py               # All env-driven settings (MT5 credentials, risk, per-strategy toggles)
│   ├── multi_symbol_targets.py # Live symbol lists + per-symbol threshold overrides per strategy
│   ├── news_analyst.py         # Shadow-mode daily bias logger (Claude API; never gates trades)
│   ├── supabase_client.py      # License validation against Supabase
│   ├── pre_live_check.py       # Pre-flight sanity checks before going live
│   ├── tray.py                 # System-tray launcher
│   ├── fetch_mt5_data.py       # One-off historical data pull from MT5
│   ├── requirements.txt
│   ├── .env                    # Local secrets (not committed) — see Configuration
│   │
│   ├── silver_bullet/          # ICT Silver Bullet strategy (M5)
│   │   ├── config.py           # All SB tunables in one dataclass
│   │   ├── strategy.py         # Signal generation: sweep → FVG → Signal dataclass
│   │   ├── indicators.py       # Swing/sweep/FVG detection
│   │   ├── live_adapter.py     # MT5 execution: limits, split TPs, BE/trail, time exit, boost mode
│   │   ├── backtest.py         # Event-driven backtesting engine
│   │   ├── metrics.py          # Sharpe, drawdown, etc.
│   │   ├── news_calendar.py    # High-impact news day detection (NFP/FOMC/CPI/GDP)
│   │   ├── plot_results.py     # Equity curve / trade visualisation
│   │   └── run_backtest.py     # CLI runner
│   │
│   ├── trendline/              # Trendline strategy (H1) — same module layout
│   │   ├── config.py  strategy.py  indicators.py  candlesticks.py
│   │   ├── live_adapter.py  backtest.py  run_backtest.py
│   │
│   ├── mutanabby/              # Mutanabby "Ultimate Algo" port (H1 SuperTrend)
│   │   ├── README.md           # Full evidence write-up — read before enabling
│   │   ├── config.py  strategy.py  indicators.py
│   │   ├── live_adapter.py  backtest.py  run_backtest.py
│   │
│   ├── src/                    # Shared utilities
│   │   ├── data_collector.py   # MT5 connect/disconnect, account info
│   │   ├── mt5_cache.py        # Per-tick shared MT5 snapshot cache
│   │   ├── ticket_store.py     # Persistent ticket attribution (bot_tickets.json)
│   │   ├── split_target.py     # Split-profit-target helpers
│   │   ├── broker_time.py      # Broker/NY time helpers
│   │   ├── paths.py            # App-data paths (frozen vs source)
│   │   └── logger.py           # Rotating file logger
│   │
│   ├── data/                   # CSV datasets and exported trade history
│   ├── backtests/              # Backtest scripts and campaign results (multi_sb_*.json etc.)
│   ├── logs/                   # Runtime logs (trades.log)
│   ├── build/  dist/  packaging/  # PyInstaller artifacts
│   └── tests/
│
├── frontend/                   # Next.js dashboard
│   ├── app/                    # page.tsx (routing/state), layout.tsx, globals.css
│   ├── screens/                # Activation, Dashboard, Trades, Performance, Settings
│   ├── components/             # Toast + dashboard section components
│   ├── lib/api.ts              # API client + mock data (works with backend offline)
│   └── package.json
│
├── deploy/                     # VPS deployment runbook and scripts
│   ├── README.md               # Full Windows VPS runbook — read before deploying
│   ├── setup_vps.ps1  install_autostart.ps1  verify_vps.py
│
└── vercel.json                 # Static frontend deploy (frontend/out)
```

---

## Strategies

### Silver Bullet (SB)

The ICT Silver Bullet intraday setup, traded on **DE30m, EURUSDm, GBPUSDm, and XAUUSDm** (top 3 of an 11-symbol, 180-day backtest campaign, with gold added 2026-08-15 after a dedicated evaluation showed PF 2.56 over the full history and 3.10 over the recent 180 days — above GBPUSDm; US30 ranked #6 and was dropped).

Active during three New York session windows (America/New_York, DST handled automatically):

| Window | NY Time | Description |
|---|---|---|
| W1 | 10:00 – 11:00 | Morning sweep |
| W2 | 11:00 – 12:00 | Continuation |
| W3 | 13:30 – 14:30 | Afternoon reversal |

An optional `SB_AGGRESSIVE` mode adds the London 03:00–05:00 windows, lowers the FVG minimum and minimum risk, and disables one-trade-per-window.

**Signal logic (two-step confirmation):**

1. **Liquidity sweep** — a confirmed swing high/low (3 bars each side) is swept within the last 10 bars and price immediately reverses. Sellside sweep → bullish bias; buyside sweep → bearish bias.
2. **Fair Value Gap (FVG)** — after the sweep, a three-candle FVG (min size scaled per symbol) in the direction of bias confirms the setup. A limit order is placed at the FVG midpoint.

**Key tunables** (`backend/silver_bullet/config.py`): breakeven at 0.25R, trail 0.1R behind best price, early exit at 0.4R adverse, deep-profit trail beyond 2R, min risk 5 pts, stop buffer 1.5 pts, news-day skip on by default.

> **Profit targets use nearest opposite liquidity** (`split_targets=False`). Split targets (TP1 3R / TP2 4R) were briefly enabled at explicit request, but measurement over the full ~17-month M5 history across the three live symbols showed they destroy the edge — the identical trades go from +$5,245 net / ~70% win rate with the liquidity target to −$940 net / ~46% with split targets (see `backend/backtests/split_compare.py`). Do not re-enable without new measurements that beat the liquidity target.

### Trendline (TL)

H1 trendline strategy on **DE30m, USDJPYm, USTECm** (disabled by default — set `TL_ENABLED=true`). Draws gently-sloping trendlines between confirmed swings, then enters at market on a trendline touch confirmed by a reversal candlestick (hammer/shooting-star/doji/railway-track). Touch tolerances are volatility-scaled per symbol (3× base on DE30m/USTECm, 1× on USDJPYm — see `multi_symbol_targets.py` for the measurements). Own magic number, own risk budget, fully independent of SB.

### Mutanabby (MB)

A faithful Python port of the TradingView "Ultimate Algo" indicator (SuperTrend flip + SMA filter on H1) on **US30m, JP225m, USDJPYm** (disabled by default — set `MB_ENABLED=true`). Sensitivity 6.0, RR 2.0, no breakeven/trailing — the exact configuration the backtest evidence supports.

> ⚠ **Read `backend/mutanabby/README.md` before enabling.** At the indicator's own default settings it loses money on every instrument tested; the live configuration sits on a soft positive ridge (median PF 1.215 across 12 instruments, ~56 trades each). This is why MB gets a deliberately small separate risk budget (default 0.25%) and is excluded from the SB/TL risk divisor.

---

## Risk Management

- **Per-strategy budgets, split across instances.** `SB_RISK_PCT` and `TL_RISK_PCT` are each divided evenly across all running SB+TL instances, so total account risk stays roughly what one pair used to risk. `MB_RISK_PCT` is divided across MB instances only, from its own budget — enabling MB can never shrink SB/TL position sizes.
- **Small-account caps.** Below `SB_SMALL_ACCT_THRESHOLD` ($150 default) each trade risks at most `SB_MAX_RISK_USD` ($1 default); no new trades below `SB_MIN_BALANCE` ($15 default). TL and MB have equivalent independent caps.
- **Circuit breakers per strategy:** daily loss limit ($10 default), max trades per day (SB 5 / TL 3 / MB 3), and a max drawdown floor (50% of starting balance) that halts trading, closes the open position, and cancels pending orders.
- **Adaptive daily-trade floor.** If combined SB+TL+MB trade count is below `DAILY_TRADE_FLOOR` (3) by `DAILY_TRADE_FLOOR_TIME_ET` (14:00 ET), SB and TL adapters relax their entry filters for the rest of the day — widening which real rule-based setups qualify, never fabricating trades.
- **Spread guard.** Entries whose stop sits closer than 1.5× the live spread are refused (a stop inside the spread is hit at the moment of fill).
- **News filter.** No new trades on high-impact US macro days (NFP/FOMC/CPI/GDP) when the per-strategy `*_NEWS` toggle is on (default).
- **Ticket persistence.** Position tickets are stored in `bot_tickets.json` so trade attribution survives broker quirks (some brokers zero out magic numbers on deals).

---

## Prerequisites

- **Windows** — MetaTrader5 Python SDK only runs on Windows
- **Python 3.11+**
- **MetaTrader 5 terminal** installed and logged in
- **Node.js 18+** and **npm** (for the frontend)
- An MT5 broker account offering the configured symbols (DE30m, EURUSDm, GBPUSDm, USDJPYm, USTECm, US30m, JP225m — suffixes vary by broker)

---

## Setup & Installation

### 1. Clone the repo

```bash
git clone https://github.com/DippsDev/AR-InvestTech.git
cd AR-InvestTech
```

### 2. Python environment

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r backend/requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
```

---

## Configuration

Create a `.env` file in the `backend/` folder (when packaged, env lives in the per-user app-data dir and is seeded from `.env.example` on first run — see `backend/src/paths.py`):

```env
# ── MT5 connection ────────────────────────────────────────────
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=YourBroker-Live
# MT5_PATH=C:\Program Files\MT5\terminal64.exe   # optional explicit path

# ── License server (Supabase) ─────────────────────────────────
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...

# ── API security ──────────────────────────────────────────────
# Required by every REST route once set. MUST be set when the
# server is reachable through a tunnel — the routes can start/stop
# live trading and overwrite the MT5 password.
API_TOKEN=
# AR_BIND_HOST=127.0.0.1   AR_BIND_PORT=8000
# AR_CORS_ORIGINS=https://ar-investech.uk,http://localhost:3000
# AR_SSL_CERTFILE=...  AR_SSL_KEYFILE=...       # optional HTTPS

# ── Silver Bullet ─────────────────────────────────────────────
SB_SYMBOL=DE30m               # display fallback; live symbols come from SB_TARGETS
SB_RISK_PCT=1.0
SB_MIN_BALANCE=15.0
SB_MAX_RISK_USD=1.0
SB_SMALL_ACCT_THRESHOLD=150.0
SB_MAX_DRAWDOWN_PCT=50.0
SB_DAILY_LOSS_LIMIT_USD=10.0
SB_MAX_TRADES_PER_DAY=5
SB_NEWS=true                  # skip high-impact news days
SB_AGGRESSIVE=false           # London windows + relaxed filters
SB_OFF_HOURS=false            # scalp outside session windows
SB_SWEEP_ENTRY=false          # enter on sweep alone (test/demo only)
SB_MIN_STOP_SPREAD_MULT=1.5
SB_GOLD_SYMBOL=XAUUSD         # dashboard read-only tile; not traded

# ── Trendline (off by default) ────────────────────────────────
TL_ENABLED=false
TL_RISK_PCT=1.0
TL_NEWS=true
TL_MAX_TRADES_PER_DAY=3
# TL_MIN_BALANCE / TL_MAX_RISK_USD / TL_SMALL_ACCT_THRESHOLD /
# TL_MAX_DRAWDOWN_PCT / TL_DAILY_LOSS_LIMIT_USD / TL_MIN_STOP_SPREAD_MULT
# mirror the SB knobs

# ── Mutanabby (off by default — read mutanabby/README.md first) ──
MB_ENABLED=false
MB_RISK_PCT=0.25
MB_NEWS=true
MB_MAX_TRADES_PER_DAY=3
# plus the same set of mirror knobs

# ── Adaptive daily-trade floor ────────────────────────────────
DAILY_TRADE_FLOOR=3
DAILY_TRADE_FLOOR_TIME_ET=14:00

# ── News Analyst (daily bias; filters entries by default) ─────
# ANTHROPIC_API_KEY=...
# NEWS_ANALYST_ENABLED=true
# NEWS_ANALYST_FILTER=true
```

> `.env` is listed in `.gitignore` and is never committed.

**Strategy tunables** live in `backend/silver_bullet/config.py`, `backend/trendline/config.py`, and `backend/mutanabby/config.py`. **Live symbol lists and per-symbol threshold overrides** live in `backend/multi_symbol_targets.py`.

---

## Running the System

### Terminal 1 — Python backend

```bash
cd backend
python server.py
```

The API starts at `http://127.0.0.1:8000` (Swagger UI at `/docs`).

### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

Dashboard opens at `http://localhost:3000`.

### Running the bot standalone (no frontend)

```bash
cd backend
python bot.py
```

Before going live, run the pre-flight checks:

```bash
cd backend
python pre_live_check.py
```

---

## API Reference

All endpoints are served by `server.py` (default `127.0.0.1:8000`). Every route requires the `API_TOKEN` shared secret when one is configured.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` | `/license` | Check if a valid license key is stored |
| `POST` | `/license/validate` | Validate (via Supabase) and persist a new license key |
| `POST` | `/mt5/connect` | Initialize the MT5 terminal connection |
| `POST` | `/bot/start` | Start the bot thread (all strategies/symbols) |
| `POST` | `/bot/stop` | Stop the bot (leaves positions open) |
| `POST` | `/bot/restart` | Restart the bot thread |
| `GET` | `/stats` | Live account stats, session info, open trades |
| `GET` | `/log` | Recent log entries (newest first) |
| `GET` | `/trades` | Closed trade history |
| `GET` | `/calendar` | News-calendar / session info |
| `GET` | `/market` | Market quotes for dashboard tickers |
| `GET` | `/settings` | Current bot/MT5 settings |
| `POST` | `/settings` | Save updated settings to `.env` (hot-reloads config) |

---

## Frontend Dashboard

Single-page app with five screens, navigated via a persistent sidebar (desktop) or slide-in drawer (mobile):

| Screen | Status | Description |
|---|---|---|
| **Activation** | Live | License key entry (validated against Supabase), MT5 connection setup |
| **Dashboard** | Live | Real-time equity, open trades across all strategies, session info, live symbol heatmap, live log |
| **Trades** | Live | Closed trade history with win/loss/all filter |
| **Performance** | In development | Equity curve, win-rate donut, monthly P&L chart |
| **Settings** | Live | MT5 credentials, per-strategy risk/toggle editor (hot-reloads backend config) |

The frontend ships with a **mock API layer** (`frontend/lib/api.ts`) so the UI is fully functional without the Python backend running.

---

## Backtesting

Each strategy has its own backtest runner:

```bash
cd backend

# Silver Bullet
python -m silver_bullet.run_backtest            # see --help for options

# Trendline
python -m trendline.run_backtest

# Mutanabby
python -m mutanabby.run_backtest --data data/us30_m5_max.csv \
    --timeframe 1h --sensitivity 6 --rr 2
```

Multi-symbol campaign results that chose the live targets are in `backend/backtests/` (`multi_sb_*.json`, `multi_tl_*.json`). Sample datasets are in `backend/data/`; pull fresh data with `python fetch_mt5_data.py`.

---

## VPS Deployment

See [`deploy/README.md`](deploy/README.md) for the full Windows VPS runbook. The critical constraint: MT5 is a GUI application that only exists inside an interactive desktop session, so the VPS must auto-logon at boot and you must **disconnect** (never "Sign out") from RDP. `bot_state.json` records the desired run state so a VPS reboot or service restart resumes trading automatically; `deploy/setup_vps.ps1`, `install_autostart.ps1`, and `verify_vps.py` automate the setup.

---

## License Activation

The app requires a license key in the format `ARB-XXXX-XXXX-XXXX`, validated against the Supabase activation server (`backend/supabase_client.py`):

1. Open the dashboard at `http://localhost:3000`
2. Enter your license key on the Activation screen
3. The key is validated remotely and stored locally
4. On subsequent launches the key is read automatically

---

## Development Notes

- **Mock vs Live**: `frontend/lib/api.ts` exports a `mockApi` object with realistic data; swap for real `fetch` calls when wiring the backend.
- **Magic numbers**: Each strategy uses its own magic number (SB: `202406122`) to distinguish its trades; position queries also cross-check the persistent ticket store because some brokers zero out magic on deals.
- **MT5 snapshot cache**: `src/mt5_cache.py` opens one snapshot window per 5-second loop tick; every adapter reads account/deals/positions/ticks from it. A periodic `[Bot] MT5 snapshot` log line reports round-trips vs cache hits.
- **Bot logger**: Logs to the app-data `logs/trades.log` via a rotating handler; `BotBridge` also routes records into the in-memory buffer served by `/log`.
- **DST handling**: Session windows use `America/New_York` via `zoneinfo`.
- **News Analyst**: `news_analyst.py` logs a daily directional bias (Claude API) once per NY day for each live SB/TL/MB symbol, then grades those calls against the next day's price. With `NEWS_ANALYST_FILTER=true` (default), live adapters only take longs on a bullish call and shorts on a bearish call; a missing or neutral call does not block. Fully disabled without an API key.

---

*Developed by DippsDev*
