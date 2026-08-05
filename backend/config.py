import os

from dotenv import load_dotenv

from src import paths

# ENV_PATH lives in the per-user app-data dir when frozen (PyInstaller), or the
# repo root when running from source — see src/paths.py. Seeded from
# .env.example on first run so a fresh install never crashes on a missing file.
ENV_PATH = paths.ensure_env_file()
# override=True: without it, dotenv refuses to overwrite an already-set
# os.environ value, so importlib.reload(config) after a Settings save (see
# bridge.py save_settings) would silently keep serving the first-ever-loaded
# values for the rest of the process's life — the .env file on disk would be
# correct but every save after the first would have no real effect.
load_dotenv(ENV_PATH, override=True)

# MT5 Connection
try:
    MT5_LOGIN = int(os.getenv("MT5_LOGIN", "0"))
except ValueError:
    MT5_LOGIN = 0
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")
# Optional explicit path to terminal64.exe (use if IPC timeout persists)
MT5_PATH     = os.getenv("MT5_PATH", "")

# Supabase activation server (service key is secret — never expose to frontend)
SUPABASE_URL          = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_KEY  = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

# ── API surface ────────────────────────────────────────────────────────────
# Shared secret required by every REST route (see server.py). Enforced only
# when non-empty, so a purely-local dev setup keeps working untouched; the
# moment the server is exposed through a tunnel this MUST be set, because
# the routes can read the MT5 login, start/stop live trading, and overwrite
# the MT5 password.
API_TOKEN = os.getenv("API_TOKEN", "").strip()

# Interface to bind. Defaults to loopback: the intended deployment puts a
# Cloudflare tunnel (or the control plane) in front, and both reach the
# server over 127.0.0.1. Set AR_BIND_HOST=0.0.0.0 only to expose it
# directly on a trusted LAN.
BIND_HOST = os.getenv("AR_BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"

try:
    BIND_PORT = int(os.getenv("AR_BIND_PORT", "8000"))
except ValueError:
    BIND_PORT = 8000

# Browser origins allowed to call this API. Comma-separated; "*" allows any.
CORS_ORIGINS = [
    o.strip() for o in os.getenv(
        "AR_CORS_ORIGINS",
        "https://ar-investech.uk,https://www.ar-investech.uk,https://ar-invest-tech.vercel.app,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",") if o.strip()
]

# Optional TLS certificate/key paths. When both are set, the API serves HTTPS.
# Useful when exposing the backend directly on a public IP behind Cloudflare
# "Full" SSL mode (self-signed origin cert) or "Full (strict)" with a valid cert.
SSL_CERTFILE = os.getenv("AR_SSL_CERTFILE", "").strip() or None
SSL_KEYFILE  = os.getenv("AR_SSL_KEYFILE", "").strip() or None

# Desired-run-state file: records whether the operator wants the bot
# trading, so a VPS reboot or service restart resumes instead of silently
# leaving the account unmanaged. See bridge.py.
BOT_STATE_FILE = str(paths.app_data_dir() / "bot_state.json")

# News Analyst — shadow-mode daily directional bias (see news_analyst.py).
# Purely observational: logs a bias call once per NY trading day for later
# evaluation. Never gates or sizes real trades. Disabled entirely (no API
# call attempted) if no key is configured.
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "").strip()
NEWS_ANALYST_ENABLED = os.getenv("NEWS_ANALYST_ENABLED", "true").lower() == "true"

# Silver Bullet — US30 (Dow Jones), active NY 10:00–12:00
# Set SB_SYMBOL in .env if your broker uses a different name (e.g. US30Cash, #US30, DJ30)
SB_SYMBOL = os.getenv("SB_SYMBOL", "US30")

# Secondary read-only market reading shown on the dashboard alongside US30 —
# not traded, just displayed. Set SB_GOLD_SYMBOL in .env if your broker uses
# a different name (e.g. XAUUSDm, GOLD, XAUUSD.a).
SB_GOLD_SYMBOL = os.getenv("SB_GOLD_SYMBOL", "XAUUSD")

# Risk parameters (editable via Settings page)
try:
    SB_RISK_PCT = float(os.getenv("SB_RISK_PCT", "1.0"))
except ValueError:
    SB_RISK_PCT = 1.0

# Minimum account balance/equity (whichever is lower) before the bot is
# allowed to open a new trade.  Default $15 gives a $100 account room for
# spread, commission and a small losing streak without margin errors.
try:
    SB_MIN_BALANCE = float(os.getenv("SB_MIN_BALANCE", "15.0"))
except ValueError:
    SB_MIN_BALANCE = 15.0

# Hard dollar cap on risk per trade while the account is small.
# Below SB_SMALL_ACCT_THRESHOLD the bot will never risk more than this
# amount on a single trade, regardless of SB_RISK_PCT.
try:
    SB_MAX_RISK_USD = float(os.getenv("SB_MAX_RISK_USD", "1.0"))
except ValueError:
    SB_MAX_RISK_USD = 1.0

try:
    SB_SMALL_ACCT_THRESHOLD = float(os.getenv("SB_SMALL_ACCT_THRESHOLD", "150.0"))
except ValueError:
    SB_SMALL_ACCT_THRESHOLD = 150.0

# Maximum allowed drawdown from the balance at bot start before the bot
# halts all trading, closes any open position and cancels pending orders.
# 50.0 = stop trading after losing 50% of the starting balance.
try:
    SB_MAX_DRAWDOWN_PCT = float(os.getenv("SB_MAX_DRAWDOWN_PCT", "50.0"))
except ValueError:
    SB_MAX_DRAWDOWN_PCT = 50.0

# Silver Bullet daily circuit breakers.
# SB_DAILY_LOSS_LIMIT_USD: stop taking new SB setups once today's realized
#   losses reach this amount (resets at the next NY trading day).
# SB_MAX_TRADES_PER_DAY: maximum number of SB trades allowed per NY day.
try:
    SB_DAILY_LOSS_LIMIT_USD = float(os.getenv("SB_DAILY_LOSS_LIMIT_USD", "10.0"))
except ValueError:
    SB_DAILY_LOSS_LIMIT_USD = 10.0

try:
    SB_MAX_TRADES_PER_DAY = int(os.getenv("SB_MAX_TRADES_PER_DAY", "5"))
except ValueError:
    SB_MAX_TRADES_PER_DAY = 5

SB_TRAIL      = os.getenv("SB_TRAIL",      "true").lower() == "true"
SB_BIAS       = os.getenv("SB_BIAS",       "false").lower() == "true"
SB_NEWS       = os.getenv("SB_NEWS",       "true").lower() == "true"
# Aggressive mode: lower signal filters + extra windows to target 2–3 trades/day
SB_AGGRESSIVE = os.getenv("SB_AGGRESSIVE", "false").lower() == "true"
# Off-hours mode: scan and trade outside defined session windows (max 3 fills/day, closes 17:00 ET)
SB_OFF_HOURS  = os.getenv("SB_OFF_HOURS",  "false").lower() == "true"
# Market order mode: enter at market immediately on signal instead of waiting for limit fill
SB_MARKET_ORDER = os.getenv("SB_MARKET_ORDER", "false").lower() == "true"
# Sweep entry mode: enter at market on sweep detection alone, no FVG required (test/demo only)
SB_SWEEP_ENTRY  = os.getenv("SB_SWEEP_ENTRY",  "false").lower() == "true"
# Refuse entries whose stop is nearer than this multiple of the live spread —
# see SilverBulletConfig.min_stop_spread_mult. 0 disables the guard.
try:
    SB_MIN_STOP_SPREAD_MULT = float(os.getenv("SB_MIN_STOP_SPREAD_MULT", "1.5"))
except ValueError:
    SB_MIN_STOP_SPREAD_MULT = 1.5

# Trendline strategy — same instrument as Silver Bullet (US30), H1 candles,
# aggressive market-order entries on trendline touch + reversal candlestick
# confirmation. Runs alongside Silver Bullet in the same bot process on the
# same symbol; fully independent (own magic number, own risk config). Off by
# default so existing installs are unaffected. bot.py always overrides this
# with whatever US30 symbol Silver Bullet resolved, so the two strategies can
# never end up trading different instruments.
TL_SYMBOL  = os.getenv("TL_SYMBOL", "US30")
TL_ENABLED = os.getenv("TL_ENABLED", "false").lower() == "true"

try:
    TL_RISK_PCT = float(os.getenv("TL_RISK_PCT", "1.0"))
except ValueError:
    TL_RISK_PCT = 1.0

try:
    TL_MIN_BALANCE = float(os.getenv("TL_MIN_BALANCE", "15.0"))
except ValueError:
    TL_MIN_BALANCE = 15.0

try:
    TL_MAX_RISK_USD = float(os.getenv("TL_MAX_RISK_USD", "1.0"))
except ValueError:
    TL_MAX_RISK_USD = 1.0

try:
    TL_SMALL_ACCT_THRESHOLD = float(os.getenv("TL_SMALL_ACCT_THRESHOLD", "150.0"))
except ValueError:
    TL_SMALL_ACCT_THRESHOLD = 150.0

try:
    TL_MAX_DRAWDOWN_PCT = float(os.getenv("TL_MAX_DRAWDOWN_PCT", "50.0"))
except ValueError:
    TL_MAX_DRAWDOWN_PCT = 50.0

try:
    TL_DAILY_LOSS_LIMIT_USD = float(os.getenv("TL_DAILY_LOSS_LIMIT_USD", "10.0"))
except ValueError:
    TL_DAILY_LOSS_LIMIT_USD = 10.0

try:
    TL_MAX_TRADES_PER_DAY = int(os.getenv("TL_MAX_TRADES_PER_DAY", "3"))
except ValueError:
    TL_MAX_TRADES_PER_DAY = 3

TL_NEWS = os.getenv("TL_NEWS", "true").lower() == "true"

# Refuse entries whose stop is nearer than this multiple of the live spread —
# see TrendlineConfig.min_stop_spread_mult. 0 disables the guard.
try:
    TL_MIN_STOP_SPREAD_MULT = float(os.getenv("TL_MIN_STOP_SPREAD_MULT", "1.5"))
except ValueError:
    TL_MIN_STOP_SPREAD_MULT = 1.5

# ---------------------------------------------------------------------------
# Mutanabby (MB) — SuperTrend flip strategy, H1
# ---------------------------------------------------------------------------
# Ported from the TradingView "Ultimate Algo" indicator; see
# backend/mutanabby/README.md for the full evidence write-up. Runs alongside
# Silver Bullet and Trendline in the same process, fully independent (own magic
# number, own risk budget). Off by default so existing installs are unaffected.
#
# RISK NOTE: the backtest support for this strategy is materially weaker than
# for SB or TL — median profit factor 1.215 across 12 instruments on only ~56
# trades each, versus SB's 2.27 on US30. MB_RISK_PCT therefore defaults to a
# deliberately small 0.25%, and MB draws from its OWN budget so enabling it can
# never reduce what SB and TL are risking (see bot.py's instance-count split).
MB_SYMBOL  = os.getenv("MB_SYMBOL", "US30m")
MB_ENABLED = os.getenv("MB_ENABLED", "false").lower() == "true"

try:
    MB_RISK_PCT = float(os.getenv("MB_RISK_PCT", "0.25"))
except ValueError:
    MB_RISK_PCT = 0.25

try:
    MB_MIN_BALANCE = float(os.getenv("MB_MIN_BALANCE", "15.0"))
except ValueError:
    MB_MIN_BALANCE = 15.0

try:
    MB_MAX_RISK_USD = float(os.getenv("MB_MAX_RISK_USD", "1.0"))
except ValueError:
    MB_MAX_RISK_USD = 1.0

try:
    MB_SMALL_ACCT_THRESHOLD = float(os.getenv("MB_SMALL_ACCT_THRESHOLD", "150.0"))
except ValueError:
    MB_SMALL_ACCT_THRESHOLD = 150.0

try:
    MB_MAX_DRAWDOWN_PCT = float(os.getenv("MB_MAX_DRAWDOWN_PCT", "50.0"))
except ValueError:
    MB_MAX_DRAWDOWN_PCT = 50.0

try:
    MB_DAILY_LOSS_LIMIT_USD = float(os.getenv("MB_DAILY_LOSS_LIMIT_USD", "10.0"))
except ValueError:
    MB_DAILY_LOSS_LIMIT_USD = 10.0

# H1 signals arrive roughly once a day per instrument, so this cap is a
# safety valve against a runaway loop rather than a routine throttle.
try:
    MB_MAX_TRADES_PER_DAY = int(os.getenv("MB_MAX_TRADES_PER_DAY", "3"))
except ValueError:
    MB_MAX_TRADES_PER_DAY = 3

MB_NEWS = os.getenv("MB_NEWS", "true").lower() == "true"

# Adaptive daily-trade floor: if by this NY time the combined SB+TL trade
# count today is still below DAILY_TRADE_FLOOR, both adapters relax their
# entry filters (smaller min risk / wider tolerances) for the rest of the
# day to raise the odds of clearing it. This never fabricates a trade —
# it only widens which real, rule-based setups qualify.
try:
    DAILY_TRADE_FLOOR = int(os.getenv("DAILY_TRADE_FLOOR", "3"))
except ValueError:
    DAILY_TRADE_FLOOR = 3
DAILY_TRADE_FLOOR_TIME_ET = os.getenv("DAILY_TRADE_FLOOR_TIME_ET", "14:00")

# Logging — paths.log_dir() creates the directory, so the handler in
# src/logger.py can open this file without a separate makedirs that would
# otherwise resolve against whatever cwd the process happened to start in.
LOG_FILE  = str(paths.log_dir() / "trades.log")
LOG_LEVEL = "INFO"
