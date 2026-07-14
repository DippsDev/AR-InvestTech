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

# Trendline strategy — EURUSD, H1 candles, aggressive market-order entries on
# trendline touch + reversal candlestick confirmation. Runs alongside Silver
# Bullet in the same bot process; fully independent (own magic number, own
# risk config). Off by default so existing installs are unaffected.
TL_SYMBOL  = os.getenv("TL_SYMBOL", "EURUSD")
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

# Logging
LOG_FILE  = str(paths.app_data_dir() / "logs" / "trades.log")
LOG_LEVEL = "INFO"
