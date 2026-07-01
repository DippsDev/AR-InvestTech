import glob
import os
import subprocess
import time

import MetaTrader5 as mt5

import config
from src.logger import logger


# Common symbol names used by brokers for the Dow Jones / US30 index.
# Exness in particular may use: US30, US30z (Zero), US30.r (Raw),
# US30.cash / US30Cash, WallStreet30, DJ30, etc.
_US30_CANDIDATES = [
    config.SB_SYMBOL,
    "US30",
    "US30z",
    "US30.r",
    "US30.cash",
    "US30Cash",
    "US30m",
    "#US30",
    "WallStreet30",
    "WALL30",
    "W30",
    "DJ30",
    "#DJ30",
    "DJIA",
    "US30Index",
]

# Errors that mean "terminal is running but not logged in with these creds".
_AUTH_ERRORS = {(-6, "Terminal: Authorization failed")}


def _kill_mt5_processes() -> None:
    """Force-close any running MT5 terminal processes."""
    for proc in ("terminal64.exe", "terminal.exe", "MetaTrader5.exe"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", proc],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception:
            pass


def _find_terminal_from_process() -> str | None:
    """Try to locate the running terminal64.exe path via wmic."""
    try:
        result = subprocess.run(
            [
                "wmic",
                "process",
                "where",
                "name='terminal64.exe'",
                "get",
                "ExecutablePath",
                "/value",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("ExecutablePath="):
                path = line.split("=", 1)[1].strip()
                if os.path.isfile(path):
                    return path
    except Exception:
        pass
    return None


def _search_common_paths() -> list[str]:
    """Search common installation directories for terminal64.exe."""
    search_roots = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
        os.environ.get("APPDATA", ""),
    ]

    candidates = []
    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue
        candidates.extend([
            os.path.join(root, "MetaTrader 5", "terminal64.exe"),
            os.path.join(root, "Exness MT5", "terminal64.exe"),
            os.path.join(root, "Exness MetaTrader 5", "terminal64.exe"),
            os.path.join(root, "Exness", "MetaTrader 5", "terminal64.exe"),
            os.path.join(root, "Exness MT5 Terminal", "terminal64.exe"),
            os.path.join(root, "MetaQuotes", "MetaTrader 5", "terminal64.exe"),
        ])

    # Quick glob search in Program Files for terminal64.exe (one level deep).
    for pf in (r"C:\Program Files", r"C:\Program Files (x86)"):
        if not os.path.isdir(pf):
            continue
        try:
            matches = glob.glob(os.path.join(pf, "*", "terminal64.exe"))
            candidates.extend(matches)
        except Exception:
            pass

    found = []
    seen = set()
    for p in candidates:
        if p and os.path.isfile(p) and p not in seen:
            seen.add(p)
            found.append(p)
    return found


def _mt5_terminal_path() -> str | None:
    """Return the best terminal64.exe path for this broker."""
    # 1. Explicit env override.
    if config.MT5_PATH and os.path.isfile(config.MT5_PATH):
        return config.MT5_PATH

    # 2. Already-running terminal.
    running = _find_terminal_from_process()
    if running:
        return running

    # 3. Common install locations.
    found = _search_common_paths()
    if not found:
        return None

    server_upper = (config.MT5_SERVER or "").upper()

    # Prefer broker-specific folders when we know the broker.
    broker_tokens = []
    if "EXNESS" in server_upper:
        broker_tokens = ["EXNESS"]

    for token in broker_tokens:
        for p in found:
            if token in p.upper():
                return p

    # Fallback: any found path.
    return found[0]


def connect_mt5(
    login: int | None = None,
    password: str | None = None,
    server: str | None = None,
    retries: int = 2,
    kill_on_timeout: bool = True,
) -> bool:
    """Initialize MT5 with retry logic and IPC-timeout recovery.

    The official MetaTrader5 Python module talks to terminal64.exe over a
    Windows named pipe. If the terminal is already logged in, passing
    credentials again can hang the pipe and return ``(-10005, 'IPC timeout')``.
    This helper therefore tries a "path-only" connection first when a terminal
    path is known, and only falls back to credentials when authorization fails.
    """
    # Ensure we are starting from a clean state on the Python side.
    try:
        mt5.shutdown()
    except Exception:
        pass

    path = _mt5_terminal_path()
    has_creds = bool(login and password and server)

    if path:
        logger.info(f"Using MT5 terminal: {path}")
    else:
        logger.warning(
            "Could not find terminal64.exe automatically. "
            "Set MT5_PATH in .env if IPC timeout persists."
        )

    last_error = None
    for attempt in range(retries + 1):
        # --- Strategy A: path only (terminal already logged in) ---
        if path:
            try:
                ok = mt5.initialize(path=path)
                if ok:
                    info = mt5.account_info()
                    if info:
                        logger.info(
                            f"Connected | Account: {info.login} | "
                            f"Balance: ${info.balance:.2f} | Server: {info.server}"
                        )
                    return True
            except Exception as exc:
                logger.warning(f"MT5 path-only initialize raised exception: {exc}")

            last_error = mt5.last_error()
            logger.warning(
                f"MT5 path-only init failed (attempt {attempt + 1}/{retries + 1}): {last_error}"
            )

            # If terminal is running but not logged in, fall through to creds.
            if has_creds and last_error in _AUTH_ERRORS:
                try:
                    mt5.shutdown()
                except Exception:
                    pass
                try:
                    ok = mt5.initialize(
                        path=path,
                        login=login,
                        password=password,
                        server=server,
                    )
                    if ok:
                        info = mt5.account_info()
                        if info:
                            logger.info(
                                f"Connected | Account: {info.login} | "
                                f"Balance: ${info.balance:.2f} | Server: {info.server}"
                            )
                        return True
                except Exception as exc:
                    logger.warning(f"MT5 credential initialize raised exception: {exc}")

                last_error = mt5.last_error()
                logger.warning(
                    f"MT5 credential init failed (attempt {attempt + 1}/{retries + 1}): {last_error}"
                )

        # --- Strategy B: credentials only (no path found / portable mode) ---
        elif has_creds:
            try:
                ok = mt5.initialize(login=login, password=password, server=server)
                if ok:
                    info = mt5.account_info()
                    if info:
                        logger.info(
                            f"Connected | Account: {info.login} | "
                            f"Balance: ${info.balance:.2f} | Server: {info.server}"
                        )
                    return True
            except Exception as exc:
                logger.warning(f"MT5 credential initialize raised exception: {exc}")

            last_error = mt5.last_error()
            logger.warning(
                f"MT5 credential init failed (attempt {attempt + 1}/{retries + 1}): {last_error}"
            )

        # --- Retry cleanup ---
        try:
            mt5.shutdown()
        except Exception:
            pass

        if kill_on_timeout and last_error == (-10005, "IPC timeout"):
            logger.warning("IPC timeout detected — terminating MT5 processes and retrying...")
            _kill_mt5_processes()
            time.sleep(5)
        else:
            time.sleep(2)

    logger.error(f"MT5 init failed after {retries + 1} attempts: {last_error}")
    return False


def disconnect_mt5() -> None:
    try:
        mt5.shutdown()
    except Exception:
        pass


def find_us30_symbol() -> str | None:
    """Search available MT5 symbols for the US30/Dow Jones instrument."""
    for name in _US30_CANDIDATES:
        if not name:
            continue
        info = mt5.symbol_info(name)
        if info is None:
            mt5.symbol_select(name, True)
            info = mt5.symbol_info(name)
        if info is not None:
            logger.info(f"Resolved US30 symbol: {name}")
            return name

    all_syms = mt5.symbols_get() or []
    for s in all_syms:
        n = s.name.upper()
        if any(token in n for token in ("US30", "DJ30", "DJIA", "WALL", "W30")):
            mt5.symbol_select(s.name, True)
            if mt5.symbol_info(s.name) is not None:
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


def list_symbols_with_details(filter_terms: list[str] | None = None) -> list[dict]:
    """Return a list of symbol details, optionally filtered by name tokens."""
    symbols = mt5.symbols_get() or []
    out = []
    for s in symbols:
        if filter_terms:
            name_upper = s.name.upper()
            if not any(term.upper() in name_upper for term in filter_terms):
                continue
        out.append({
            "name": s.name,
            "visible": s.visible,
            "description": s.description,
            "point": s.point,
            "digits": s.digits,
            "volume_min": s.volume_min,
            "volume_max": s.volume_max,
            "volume_step": s.volume_step,
            "trade_stops_level": s.trade_stops_level,
            "trade_tick_value": s.trade_tick_value,
            "trade_tick_size": s.trade_tick_size,
            "spread": s.spread,
        })
    return out
