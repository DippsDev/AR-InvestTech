import MetaTrader5 as mt5

import config
from src.logger import logger


def connect_mt5() -> bool:
    if not mt5.initialize():
        logger.error(f"MT5 init failed: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    if info:
        logger.info(
            f"Connected | Account: {info.login} | Balance: ${info.balance:.2f} | Server: {info.server}"
        )
    return True


def disconnect_mt5() -> None:
    mt5.shutdown()


def find_us30_symbol() -> str | None:
    """Search available MT5 symbols for the US30/Dow Jones instrument."""
    priority = [config.SB_SYMBOL, "US30", "US30Cash", "#US30", "DJ30", "DJIA", "US30m", "#DJ30"]
    for name in priority:
        if mt5.symbol_info(name) is not None:
            logger.info(f"Resolved US30 symbol: {name}")
            return name
    all_syms = mt5.symbols_get() or []
    for s in all_syms:
        n = s.name.upper()
        if ("US30" in n or "DJ30" in n or "DJIA" in n) and "USD" in n:
            logger.info(f"Resolved US30 symbol (search): {s.name}")
            return s.name
    logger.warning("No US30 symbol found. Set SB_SYMBOL in .env to the correct name.")
    return None


def get_account_info() -> dict | None:
    info = mt5.account_info()
    if info is None:
        return None
    return {
        "balance":      info.balance,
        "equity":       info.equity,
        "margin":       info.margin,
        "free_margin":  info.margin_free,
        "profit":       info.profit,
        "margin_level": info.margin_level,
    }
