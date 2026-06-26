import os
from dotenv import load_dotenv

load_dotenv()

# MT5 Connection
MT5_LOGIN    = int(os.getenv("MT5_LOGIN", "0"))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER   = os.getenv("MT5_SERVER", "")

# Silver Bullet — US30 (Dow Jones), active NY 10:00–12:00
# Set SB_SYMBOL in .env if your broker uses a different name (e.g. US30Cash, #US30, DJ30)
SB_SYMBOL = os.getenv("SB_SYMBOL", "US30")

# Risk parameters (editable via Settings page)
SB_RISK_PCT   = os.getenv("SB_RISK_PCT",   "1.0")
SB_DAILY_CAP  = os.getenv("SB_DAILY_CAP",  "3.0")
SB_MAX_TRADES = os.getenv("SB_MAX_TRADES", "1")
SB_TRAIL      = os.getenv("SB_TRAIL",      "true").lower() == "true"
SB_BIAS       = os.getenv("SB_BIAS",       "false").lower() == "true"
SB_NEWS       = os.getenv("SB_NEWS",       "false").lower() == "true"
# Aggressive mode: lower signal filters + extra windows to target 2–3 trades/day
SB_AGGRESSIVE = os.getenv("SB_AGGRESSIVE", "false").lower() == "true"
# Off-hours mode: scan and trade outside defined session windows (max 3 fills/day, closes 17:00 ET)
SB_OFF_HOURS  = os.getenv("SB_OFF_HOURS",  "false").lower() == "true"

# Logging
LOG_FILE  = "logs/trades.log"
LOG_LEVEL = "INFO"
