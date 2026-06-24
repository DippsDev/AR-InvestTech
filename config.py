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

# Logging
LOG_FILE  = "logs/trades.log"
LOG_LEVEL = "INFO"
