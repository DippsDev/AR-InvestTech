# AR-InvestTech

A full-stack algorithmic trading system for the **US30 (Dow Jones)** index. It implements the **ICT Silver Bullet** strategy on M5 candles, executes live trades through **MetaTrader 5**, and exposes a real-time monitoring dashboard built with **Next.js**.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Strategy — ICT Silver Bullet](#strategy--ict-silver-bullet)
- [Prerequisites](#prerequisites)
- [Setup & Installation](#setup--installation)
- [Configuration](#configuration)
- [Running the System](#running-the-system)
- [API Reference](#api-reference)
- [Frontend Dashboard](#frontend-dashboard)
- [Backtesting](#backtesting)
- [License Activation](#license-activation)

---

## Overview

| Layer | Technology | Purpose |
|---|---|---|
| Strategy engine | Python + NumPy/Pandas | Signal generation, backtesting |
| Execution adapter | MetaTrader5 Python SDK | Live order placement and management |
| Backend API | FastAPI + Uvicorn | REST bridge between bot and frontend |
| Frontend | Next.js 16 + React 19 + Tailwind v4 | Real-time dashboard (monitor, control, trade log) |

The bot runs as a background thread managed by the FastAPI server. The frontend polls the API to display live stats, log entries, and trade history.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Frontend                             │
│         Next.js 16  ·  React 19  ·  Tailwind CSS v4        │
│                    http://localhost:3000                     │
└───────────────────────────┬─────────────────────────────────┘
                            │  REST  (CORS: localhost:3000)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Server                          │
│                   server.py  ·  :8000                       │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    BotBridge                         │   │
│  │  bridge.py — license · MT5 connection · bot thread  │   │
│  └────────────────────────┬─────────────────────────────┘   │
└───────────────────────────┼─────────────────────────────────┘
                            │
          ┌─────────────────┘
          │
┌─────────▼──────────────────────────────────────────────────┐
│                   SilverBulletBot                          │
│                      bot.py                                │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           silver_bullet/live_adapter.py              │  │
│  │   Fetches M5 bars → SignalGenerator → MT5 orders    │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │           silver_bullet/strategy.py                  │  │
│  │   Sweep detection → FVG confirmation → Signal()     │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────┬───────────────────────────────┘
                             │ MetaTrader5 Python SDK
                             ▼
                    ┌────────────────┐
                    │  MT5 Terminal  │
                    │   US30 Live    │
                    └────────────────┘
```

---

## Project Structure

```
ar-investments/
│
├── bot.py                    # Bot entry point — runs standalone or via bridge
├── bridge.py                 # Shared business logic (license, MT5, bot lifecycle, log)
├── server.py                 # FastAPI REST API — run this to serve the frontend
├── config.py                 # Environment config (MT5 credentials, symbol, log path)
├── requirements.txt          # Python dependencies
├── .env                      # Local secrets (not committed) — see Configuration
│
├── silver_bullet/            # Strategy module
│   ├── config.py             # All strategy tunables in one dataclass
│   ├── strategy.py           # Signal generation: sweep → FVG → Signal dataclass
│   ├── indicators.py         # Swing detection, sweep detection, FVG detection
│   ├── live_adapter.py       # MT5 execution: places limits, manages BE/trail/time-exit
│   ├── backtest.py           # Event-driven backtesting engine
│   ├── data.py               # Historical bar fetching from MT5
│   ├── metrics.py            # Backtest performance metrics (Sharpe, drawdown, etc.)
│   ├── news_calendar.py      # High-impact news day detection (NFP/FOMC/CPI/GDP)
│   ├── plot_results.py       # Matplotlib equity curve and trade visualisation
│   ├── run_backtest.py       # CLI runner for backtests
│   └── tests/
│       └── test_indicators.py
│
├── src/                      # Shared utilities
│   ├── data_collector.py     # MT5 connect/disconnect, account info, symbol lookup
│   └── logger.py             # Rotating file logger (logs/trades.log)
│
├── logs/
│   └── trades.log            # Runtime log output
│
├── trades.csv                # Exported trade history (optional)
├── us30_m5_200d.csv          # Sample US30 M5 data (200 days)
├── us30_m5_3y.csv            # Sample US30 M5 data (3 years)
├── fetch_mt5_data.py         # One-off script to pull historical data from MT5
├── optimize.py               # Parameter optimisation script
│
└── frontend/                 # Next.js dashboard
    ├── app/
    │   ├── page.tsx          # Root app: routing, state, title bar, sidebar, drawer
    │   ├── layout.tsx        # HTML shell, fonts, metadata
    │   └── globals.css       # Global styles, layout classes, responsive breakpoints
    ├── screens/
    │   ├── Activation.tsx    # License key entry screen
    │   ├── Dashboard.tsx     # Live stats, active trade, session info, live log
    │   ├── Trades.tsx        # Closed trade history with filter
    │   ├── Performance.tsx   # Equity curve, win/loss donut, monthly P&L (WIP)
    │   └── Settings.tsx      # MT5 credentials and bot parameter editor
    ├── lib/
    │   └── api.ts            # API client + mock data (used when backend is offline)
    ├── components/
    │   └── Toast.tsx         # Toast notification component
    └── package.json
```

---

## Strategy — ICT Silver Bullet

The Silver Bullet is an **ICT (Inner Circle Trader)** intraday setup. It trades **US30 on M5** and is only active during three New York session windows:

| Window | NY Time | Description |
|---|---|---|
| W1 | 10:00 – 11:00 | Morning sweep |
| W2 | 11:00 – 12:00 | Continuation |
| W3 | 13:30 – 14:30 | Afternoon reversal |

### Signal Logic (two-step confirmation)

**Step 1 — Liquidity Sweep**
The bot scans for a confirmed swing high/low (3 bars each side) that is **swept** by price within the last 10 bars, then immediately reverses. A sellside sweep → bullish bias; a buyside sweep → bearish bias.

**Step 2 — Fair Value Gap (FVG)**
After the sweep, the bot looks for a **three-candle FVG** (minimum 8 pts) in the direction of bias. On confirmation, a **limit order** is placed at the midpoint of the FVG.

### Trade Management

| Parameter | Default | Description |
|---|---|---|
| Risk per trade | 1% of balance | Lot size calculated automatically |
| Stop loss | Swept extreme ± 1 pt buffer | Behind the sweep level |
| Target | Nearest opposite liquidity | Falls back to 2R if no pool found |
| Breakeven | 0.5R in profit | Stop moves to entry |
| Trailing stop | 0.25R behind best price | Activates after breakeven |
| Deep-profit trail | 0.1R when > 2R in profit | Tighter trail on large winners |
| Time exit | End of active window | Forces flat if still in trade |
| One trade per window | Yes | Prevents overtrading |

---

## Prerequisites

- **Windows** — MetaTrader5 Python SDK only runs on Windows
- **Python 3.11+**
- **MetaTrader 5 terminal** installed and logged in
- **Node.js 18+** and **npm** (for the frontend)
- An MT5 broker account with US30/DJ30/WALL30 available

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
pip install -r requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
```

---

## Configuration

Create a `.env` file in the project root (next to `server.py`):

```env
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=YourBroker-Live

# Optional: override if your broker uses a different symbol name
# Common variants: US30Cash, #US30, DJ30, WALL30
SB_SYMBOL=US30

# Small-account safety floor (balance or equity must be above this value)
# For a $100 account the default $15 is recommended.
SB_MIN_BALANCE=15.0

# Hard dollar cap per trade while balance/equity is below $150.
SB_MAX_RISK_USD=1.0
SB_SMALL_ACCT_THRESHOLD=150.0

# Maximum drawdown from the balance at bot start before the bot halts
# all trading and closes any open position.
SB_MAX_DRAWDOWN_PCT=50.0
```

> `.env` is listed in `.gitignore` and is never committed.

**Strategy tunables** live in [`silver_bullet/config.py`](silver_bullet/config.py) as a single `SilverBulletConfig` dataclass. Edit that file to adjust swing lookback, FVG minimum size, R:R ratio, trail parameters, etc.

---

## Running the System

Both the backend server and the frontend dev server must be running at the same time.

### Terminal 1 — Python backend

```bash
# From the project root, with .venv activated
python server.py
```

The API starts at `http://127.0.0.1:8000`. Visit `http://127.0.0.1:8000/docs` for the interactive Swagger UI.

### Terminal 2 — Frontend

```bash
cd frontend
npm run dev
```

Dashboard opens at `http://localhost:3000`.

### Running the bot standalone (no frontend)

```bash
python bot.py
```

---

## API Reference

All endpoints are served by `server.py` on port `8000`.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/license` | Check if a valid license key is stored |
| `POST` | `/license/validate` | Validate and persist a new license key |
| `POST` | `/mt5/connect` | Initialize the MT5 terminal connection |
| `POST` | `/bot/start` | Start the Silver Bullet bot thread |
| `POST` | `/bot/stop` | Stop the bot (leaves positions open) |
| `GET` | `/stats` | Live account stats, session info, open trade |
| `GET` | `/log` | Last 40 log entries (newest first) |
| `GET` | `/trades` | Closed trade history (last 30 days) |
| `GET` | `/settings` | Current bot/MT5 settings |
| `POST` | `/settings` | Save updated settings to `.env` |

---

## Frontend Dashboard

The dashboard is a single-page app with five screens, navigated via a persistent sidebar (desktop) or slide-in drawer (mobile):

| Screen | Status | Description |
|---|---|---|
| **Activation** | Live | License key entry, MT5 connection setup |
| **Dashboard** | Live | Real-time equity, open trade details, session info, live log with expand view |
| **Trades** | Live | Closed trade history with win/loss/all filter |
| **Performance** | In development | Equity curve, win-rate donut, monthly P&L chart |
| **Settings** | Live | MT5 login/server editor, bot parameter toggles |

The frontend ships with a **mock API layer** (`frontend/lib/api.ts`) so the UI is fully functional and usable without the Python backend running — useful for UI development and demos.

---

## Backtesting

```bash
# Run a backtest on the sample 3-year dataset
python silver_bullet/run_backtest.py

# Optimise strategy parameters
python optimize.py
```

Backtest results are plotted with Matplotlib (`silver_bullet/plot_results.py`) showing the equity curve and per-trade annotations. Sample datasets are included:

- `us30_m5_200d.csv` — 200 days of US30 M5 data
- `us30_m5_3y.csv` — 3 years of US30 M5 data

To pull fresh data directly from your MT5 terminal:

```bash
python fetch_mt5_data.py
```

---

## License Activation

The app requires a license key in the format `ARB-XXXX-XXXX-XXXX`. On first launch:

1. Open the dashboard at `http://localhost:3000`
2. Enter your license key on the Activation screen
3. The key is validated and stored in a local `.license` file
4. On subsequent launches the key is read automatically

> The activation server integration is stubbed (`TODO` in `bridge.py`). Any key matching the `ARB-XXXX-XXXX-XXXX` format is currently accepted.

---

## Development Notes

- **Mock vs Live**: `frontend/lib/api.ts` exports a `mockApi` object with realistic US30 data. When wiring up the real backend, swap `mockApi` calls in `page.tsx` for `fetch` calls to the FastAPI endpoints.
- **Magic number**: Live bot orders use magic number `202406122` to distinguish them from manual trades. All position queries filter by this magic number.
- **Bot logger**: The bot logs to `logs/trades.log` via a rotating file handler. The `BotBridge` in `bridge.py` also intercepts these log records and routes them into the in-memory log buffer that `/log` serves to the frontend.
- **DST handling**: Session windows use `America/New_York` via `zoneinfo` — daylight saving is handled automatically.

---

*Developed by DippsDev*
