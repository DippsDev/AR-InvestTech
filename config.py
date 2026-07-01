import os
from dotenv import load_dotenv

load_dotenv()

# MT5 Connection
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")
# Optional explicit path to terminal64.exe (use if IPC timeout persists)
MT5_PATH     = os.getenv("MT5_PATH", "")

# Silver Bullet — US30 (Dow Jones), active NY 10:00–12:00
# Set SB_SYMBOL in .env if your broker uses a different name (e.g. US30Cash, #US30, DJ30)
SB_SYMBOL = os.getenv("SB_SYMBOL", "US30")

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
    SB_DAILY_LOSS_LIMIT_USD = float(os.getenv("SB_DAILY_LOSS_LIMIT_USD", "3.0"))
except ValueError:
    SB_DAILY_LOSS_LIMIT_USD = 3.0

try:
    SB_MAX_TRADES_PER_DAY = int(os.getenv("SB_MAX_TRADES_PER_DAY", "2"))
except ValueError:
    SB_MAX_TRADES_PER_DAY = 2

SB_DAILY_CAP  = os.getenv("SB_DAILY_CAP",  "3.0")
SB_MAX_TRADES = os.getenv("SB_MAX_TRADES", "1")
SB_TRAIL      = os.getenv("SB_TRAIL",      "true").lower() == "true"
SB_BIAS       = os.getenv("SB_BIAS",       "false").lower() == "true"
SB_NEWS       = os.getenv("SB_NEWS",       "false").lower() == "true"
# Aggressive mode: lower signal filters + extra windows to target 2–3 trades/day
SB_AGGRESSIVE = os.getenv("SB_AGGRESSIVE", "false").lower() == "true"
# Off-hours mode: scan and trade outside defined session windows (max 3 fills/day, closes 17:00 ET)
SB_OFF_HOURS  = os.getenv("SB_OFF_HOURS",  "false").lower() == "true"
# Market order mode: enter at market immediately on signal instead of waiting for limit fill
SB_MARKET_ORDER = os.getenv("SB_MARKET_ORDER", "false").lower() == "true"
# Sweep entry mode: enter at market on sweep detection alone, no FVG required (test/demo only)
SB_SWEEP_ENTRY  = os.getenv("SB_SWEEP_ENTRY",  "false").lower() == "true"

# Logging
LOG_FILE  = "logs/trades.log"
LOG_LEVEL = "INFO"
