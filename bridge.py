"""
Bot bridge — business logic shared by server.py (FastAPI REST backend).
Handles license validation, MT5 connection, bot lifecycle, and live data.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

LICENSE_FILE = Path(".license")


# ── Log capture ─────────────────────────────────────────────────────────────

class _BotLogHandler(logging.Handler):
    """Intercepts the bot logger and routes entries into the log buffer."""

    TAG_MAP = {
        "LIMIT":     ("[ENTRY]", "win"),
        "filled":    ("[ENTRY]", "win"),
        "open":      ("[ENTRY]", "win"),
        "Breakeven": ("[BE]",    "sig"),
        "Trail":     ("[TRAIL]", "sig"),
        "trail":     ("[TRAIL]", "sig"),
        "cancel":    ("[INFO]",  "inf"),
        "Cancel":    ("[INFO]",  "inf"),
        "Time exit": ("[EXIT]",  "inf"),
        "closed":    ("[EXIT]",  "inf"),
        "Error":     ("[ERR]",   "warn"),
        "failed":    ("[ERR]",   "warn"),
        "START":     ("[START]", "win"),
        "STOP":      ("[STOP]",  "inf"),
        "Signal":    ("[SIG]",   "sig"),
        "signal":    ("[SIG]",   "sig"),
        "Scanning":  ("[SCAN]",  "inf"),
    }

    def __init__(self, bridge: "BotBridge") -> None:
        super().__init__()
        self._bridge = bridge
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            tag, kind = "[INFO]", "inf"
            for keyword, mapping in self.TAG_MAP.items():
                if keyword in msg:
                    tag, kind = mapping
                    break
            clean = msg
            for prefix in ["[SB] ", "AR Investments — "]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
            self._bridge._add_log(tag, kind, clean)
        except Exception:
            pass


# ── Bridge ───────────────────────────────────────────────────────────────────

class BotBridge:
    def __init__(self) -> None:
        self._bot = None
        self._bot_thread: Optional[threading.Thread] = None
        self._bot_running = False
        self._log_buffer: list[dict] = []
        self._lock = threading.Lock()
        self._start_time: Optional[float] = None
        self._mt5_ok = False
        self._log_handler: Optional[_BotLogHandler] = None

    # ── License ──────────────────────────────────────────────────────────────

    def check_license(self) -> dict:
        if not LICENSE_FILE.exists():
            return {"ok": False}
        key = LICENSE_FILE.read_text().strip()
        valid = key.startswith("ARB-") and len(key) == 19
        return {"ok": valid, "key": key if valid else ""}

    def validate_license(self, key: str) -> dict:
        key = str(key).strip().upper()
        if not key.startswith("ARB-") or len(key) != 19:
            return {"ok": False, "error": "Invalid format. Expected ARB-XXXX-XXXX-XXXX"}
        # TODO: HTTP call to activation server goes here
        LICENSE_FILE.write_text(key)
        return {"ok": True, "key": key}

    # ── MT5 connection ────────────────────────────────────────────────────────

    def connect_mt5(self) -> dict:
        try:
            from src.data_collector import connect_mt5 as _connect_mt5
            ok = _connect_mt5(retries=2)
            if not ok:
                import MetaTrader5 as mt5
                self._mt5_ok = False
                return {"ok": False, "error": str(mt5.last_error())}
            import MetaTrader5 as mt5
            info = mt5.account_info()
            self._mt5_ok = True
            self._add_log("[MT5]", "win", f"Connected · {info.server}" if info else "Connected")
            return {
                "ok":      True,
                "login":   str(info.login) if info else "",
                "server":  info.server if info else "",
                "balance": f"${info.balance:,.2f}" if info else "--",
            }
        except Exception as exc:
            self._mt5_ok = False
            return {"ok": False, "error": str(exc)}

    # ── Bot lifecycle ─────────────────────────────────────────────────────────

    def _start_bot(self) -> None:
        from bot import SilverBulletBot
        self._bot = SilverBulletBot(gui_mode=True)
        log = logging.getLogger("silver_bullet_bot")
        self._log_handler = _BotLogHandler(self)
        log.addHandler(self._log_handler)
        self._bot_thread = threading.Thread(target=self._bot.run, daemon=True)
        self._bot_thread.start()
        self._bot_running = True
        self._start_time = time.time()
        self._add_log("[START]", "win", "Bot started · scanning US30 for Silver Bullet setups")

    def _stop_bot(self) -> None:
        if self._bot:
            self._bot.running = False
        self._bot_running = False
        if self._log_handler:
            logging.getLogger("silver_bullet_bot").removeHandler(self._log_handler)
            self._log_handler = None
        self._add_log("[STOP]", "inf", "Bot stopped by user · positions held open")

    def _is_running(self) -> bool:
        return self._bot_running and bool(self._bot_thread and self._bot_thread.is_alive())

    # ── Live stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        running   = self._is_running()
        account   = self._get_account()
        positions = self._get_positions()

        balance = account["balance"] if account else 0.0
        equity  = account["equity"]  if account else 0.0
        profit  = account["profit"]  if account else 0.0

        open_trade = None
        if positions:
            try:
                import MetaTrader5 as mt5
                pos = positions[0]
                breakeven_set = (
                    (pos.sl >= pos.price_open if pos.type == mt5.ORDER_TYPE_BUY else pos.sl <= pos.price_open)
                    if pos.sl != 0 else False
                )
                open_trade = {
                    "symbol":    pos.symbol,
                    "side":      "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                    "entry":     f"{pos.price_open:,.2f}",
                    "sl":        f"{pos.sl:,.2f}" if pos.sl else "—",
                    "tp":        f"{pos.tp:,.2f}" if pos.tp else "—",
                    "float_pnl": f"+${pos.profit:.2f}" if pos.profit >= 0 else f"-${abs(pos.profit):.2f}",
                    "lots":      f"{pos.volume:.2f}",
                    "breakeven": breakeven_set,
                }
            except Exception:
                pass

        next_refresh = "--"
        if running and self._start_time:
            elapsed = (time.time() - self._start_time) % 30
            next_refresh = f"{max(1, int(30 - elapsed))}s"

        try:
            import config as _cfg
            from zoneinfo import ZoneInfo
            from silver_bullet.config import SilverBulletConfig
            cfg = SilverBulletConfig()
            if _cfg.SB_AGGRESSIVE:
                cfg.windows = [
                    ("03:00", "04:00"), ("04:00", "05:00"),
                    ("10:00", "11:00"), ("11:00", "12:00"),
                ]
            if _cfg.SB_OFF_HOURS:
                cfg.off_hours_trading = True
            ny_h = datetime.now(ZoneInfo("America/New_York")).hour

            session = "Off-Hours"
            for start_s, end_s in cfg.windows:
                sh, sm = map(int, start_s.split(":"))
                eh, em = map(int, end_s.split(":"))
                start_h = sh + sm / 60.0
                end_h = eh + em / 60.0
                if start_h <= ny_h < end_h:
                    session = f"NY {start_s}–{end_s} (Active)"
                    break
            if session == "Off-Hours" and _cfg.SB_OFF_HOURS and ny_h < 17:
                session = "Off-Hours (Active)"
        except Exception:
            session = "--"

        import config as _cfg
        import MetaTrader5 as mt5
        from datetime import datetime, timezone
        market_open = False
        if self._mt5_ok and _cfg.SB_SYMBOL:
            tick = mt5.symbol_info_tick(_cfg.SB_SYMBOL)
            sym = mt5.symbol_info(_cfg.SB_SYMBOL)
            if tick is not None and sym is not None and sym.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
                last_tick = datetime.fromtimestamp(tick.time, tz=timezone.utc)
                market_open = (datetime.now(tz=timezone.utc) - last_tick).total_seconds() < 300
        return {
            "running":        running,
            "connected":      self._mt5_ok,
            "balance":        f"${balance:,.2f}" if account else "--",
            "equity":         f"${equity:,.2f}"  if account else "--",
            "profit":         (f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}") if account else "--",
            "open_trades":    str(len(positions)),
            "open_trade":     open_trade,
            "next_refresh":   next_refresh,
            "session":        session,
            "daily_cap_used": "--",
            "symbol":         _cfg.SB_SYMBOL,
            "risk_pct":       str(_cfg.SB_RISK_PCT),
            "max_trades":     _cfg.SB_MAX_TRADES,
            "timeframe":      "M5",
            "market_open":    market_open,
        }

    def _get_account(self) -> Optional[dict]:
        if not self._mt5_ok:
            return None
        try:
            import MetaTrader5 as mt5
            info = mt5.account_info()
            return {"balance": info.balance, "equity": info.equity, "profit": info.profit} if info else None
        except Exception:
            return None

    def _get_positions(self) -> list:
        if not self._mt5_ok:
            return []
        try:
            import MetaTrader5 as mt5
            from silver_bullet.live_adapter import SB_MAGIC
            return [p for p in (mt5.positions_get() or []) if p.magic == SB_MAGIC]
        except Exception:
            return []

    # ── Log ──────────────────────────────────────────────────────────────────

    def get_log(self) -> list:
        with self._lock:
            return list(reversed(self._log_buffer[-40:]))

    def _add_log(self, tag: str, kind: str, text: str) -> None:
        t = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._log_buffer.append({"t": t, "tag": tag, "k": kind, "x": text})
            if len(self._log_buffer) > 200:
                self._log_buffer = self._log_buffer[-200:]

    # ── Trade history ─────────────────────────────────────────────────────────

    def get_trades(self) -> list:
        if not self._mt5_ok:
            return []
        try:
            import MetaTrader5 as mt5
            from silver_bullet.live_adapter import SB_MAGIC
            from_dt = datetime.now() - timedelta(days=30)
            deals = mt5.history_deals_get(from_dt, datetime.now()) or []

            opens, closes = {}, []
            for d in deals:
                if d.magic != SB_MAGIC:
                    continue
                if d.entry == mt5.DEAL_ENTRY_IN:
                    opens[d.position_id] = d
                elif d.entry == mt5.DEAL_ENTRY_OUT and d.position_id in opens:
                    closes.append((opens.pop(d.position_id), d))

            rows = []
            for o, c in reversed(closes):
                pnl  = c.profit
                side = "BUY" if o.type == mt5.DEAL_TYPE_BUY else "SELL"
                pts  = round((c.price - o.price) * (1 if side == "BUY" else -1), 2)
                rows.append({
                    "id":       f"#{c.position_id}",
                    "date":     datetime.fromtimestamp(c.time).strftime("%b %d"),
                    "side":     side,
                    "lots":     f"{c.volume:.2f}",
                    "entry":    f"{o.price:,.2f}",
                    "exit":     f"{c.price:,.2f}",
                    "pips":     f"{'+' if pts >= 0 else ''}{pts:.0f}",
                    "pnl":      round(pnl, 2),
                    "win":      pnl > 0,
                    "pnl_text": f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}",
                })
            return rows
        except Exception:
            return []

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        import config
        return {
            "login":                str(config.MT5_LOGIN),
            "server":               config.MT5_SERVER,
            "symbol":               config.SB_SYMBOL,
            "risk_pct":             str(config.SB_RISK_PCT),
            "daily_loss_limit_usd": str(config.SB_DAILY_LOSS_LIMIT_USD),
            "max_trades_per_day":   str(config.SB_MAX_TRADES_PER_DAY),
            "max_drawdown_pct":     str(config.SB_MAX_DRAWDOWN_PCT),
            "aggressive":           config.SB_AGGRESSIVE,
            "off_hours":            config.SB_OFF_HOURS,
        }

    def save_settings(self, data: dict) -> dict:
        try:
            env_path = Path(".env")
            raw = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
            env: dict[str, str] = {}
            for line in raw.splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
            mapping = {
                "login":                "MT5_LOGIN",
                "server":               "MT5_SERVER",
                "symbol":               "SB_SYMBOL",
                "risk_pct":             "SB_RISK_PCT",
                "daily_loss_limit_usd": "SB_DAILY_LOSS_LIMIT_USD",
                "max_trades_per_day":   "SB_MAX_TRADES_PER_DAY",
                "max_drawdown_pct":     "SB_MAX_DRAWDOWN_PCT",
                "aggressive":           "SB_AGGRESSIVE",
                "off_hours":            "SB_OFF_HOURS",
            }
            for field, env_key in mapping.items():
                if field in data:
                    val = data[field]
                    env[env_key] = str(val).lower() if isinstance(val, bool) else str(val)
            env_path.write_text("\n".join(f"{k}={v}" for k, v in env.items()), encoding="utf-8")
            # Reload config so next get_settings() call reflects the saved values
            import importlib, config as cfg
            importlib.reload(cfg)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
