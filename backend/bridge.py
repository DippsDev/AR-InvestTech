"""
Bot bridge — business logic shared by server.py (FastAPI REST backend).
Handles license validation, MT5 connection, bot lifecycle, and live data.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from src import paths

import config
import machine_id
import supabase_client

LICENSE_FILE = paths.app_data_dir() / ".license"


# ── Log capture ─────────────────────────────────────────────────────────────
#
# The bot's real logger (src/logger.py) is extremely chatty — every ~30s cycle
# emits a dozen diagnostic lines ("Cycle start", "Syncing fill status", ...).
# Those still go to the file/console logger untouched. The dashboard feed only
# gets the decision-worthy subset below, each attributed to the "persona" that
# owns that kind of decision (Trader/Risk/News Guard/Scanner/Boss), so the
# activity feed reads as a handful of roles narrating real outcomes instead of
# a raw debug trace. Unmatched (diagnostic) lines are dropped, not defaulted.

class _BotLogHandler(logging.Handler):
    """Intercepts the bot logger and routes decision-worthy entries into the log buffer."""

    TAG_MAP = {
        # Analyst entries first: several share substrings ("No tick data",
        # "failed") with generic Scanner/Risk rules below, and the first
        # matching keyword wins.
        "Analyst] Bias":            ("[BIAS]",  "sig",  "Analyst"),
        "Analyst] Graded":          ("[GRADE]", "inf",  "Analyst"),
        "Analyst] No tick data":    ("[INFO]",  "inf",  "Analyst"),
        "Analyst] Daily bias check failed": ("[ERR]", "warn", "Analyst"),
        "CIRCUIT BREAKER":          ("[HALT]",  "warn", "Boss"),
        "Daily loss limit reached": ("[RISK]",  "warn", "Risk"),
        "Daily trade cap reached":  ("[RISK]",  "warn", "Risk"),
        "Off-hours cap":            ("[RISK]",  "warn", "Risk"),
        "Drawdown floor set":       ("[RISK]",  "sig",  "Risk"),
        "Daily limits reset":       ("[RISK]",  "inf",  "Risk"),
        "high-impact news day":     ("[NEWS]",  "warn", "News Guard"),
        "News day":                 ("[NEWS]",  "warn", "News Guard"),
        "LIMIT":                    ("[ENTRY]", "win",  "Trader"),
        "filled":                   ("[ENTRY]", "win",  "Trader"),
        "Breakeven":                ("[BE]",    "sig",  "Trader"),
        "Trail":                    ("[TRAIL]", "sig",  "Trader"),
        "closed by MT5":            ("[EXIT]",  "inf",  "Trader"),
        "Time exit":                ("[EXIT]",  "inf",  "Trader"),
        "removed without fill":     ("[INFO]",  "inf",  "Trader"),
        "cancelled (window ended)": ("[INFO]",  "inf",  "Trader"),
        "No setup on":              ("[SCAN]",  "inf",  "Scanner"),
        "Signal stale":             ("[INFO]",  "inf",  "Scanner"),
        "Market closed for":        ("[INFO]",  "inf",  "Scanner"),
        "Bar fetch failed":         ("[ERR]",   "warn", "Scanner"),
        "order failed":             ("[ERR]",   "warn", "Scanner"),
        "not found":                ("[ERR]",   "warn", "Scanner"),
        "No tick data":             ("[ERR]",   "warn", "Scanner"),
    }

    def __init__(self, bridge: "BotBridge") -> None:
        super().__init__()
        self._bridge = bridge
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            match = None
            for keyword, mapping in self.TAG_MAP.items():
                if keyword in msg:
                    match = mapping
                    break
            if match is None:
                return  # diagnostic-only line — not decision-worthy, skip the feed
            tag, kind, speaker = match
            clean = msg
            for prefix in ["[SB] ", "AR Investments — "]:
                if clean.startswith(prefix):
                    clean = clean[len(prefix):]
            self._bridge._add_log(tag, kind, clean, speaker=speaker)
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
        self._graded_ids: set[str] = set()
        self._graded_seeded = False

    # ── License ──────────────────────────────────────────────────────────────

    def check_license(self) -> dict:
        if not LICENSE_FILE.exists():
            return {"ok": False}
        key = LICENSE_FILE.read_text().strip()
        valid = key.startswith("ARB-") and len(key) == 18
        return {"ok": valid, "key": key if valid else ""}

    def validate_license(self, key: str) -> dict:
        key = str(key).strip().upper()
        if not key.startswith("ARB-") or len(key) != 18:
            return {"ok": False, "error": "Invalid format. Expected ARB-XXXX-XXXX-XXXX"}

        # If Supabase is not configured, fall back to local-only validation.
        if not supabase_client.is_configured():
            LICENSE_FILE.write_text(key)
            return {"ok": True, "key": key}

        return self._validate_license_online(key)

    def _validate_license_online(self, key: str) -> dict:
        sb = supabase_client.get_supabase()
        if sb is None:
            return {"ok": False, "error": "Activation server is not configured."}

        try:
            # 1. Fetch the license row.
            resp = sb.table("licenses").select("*").eq("key", key).execute()
            rows = resp.data or []
            if not rows:
                return {"ok": False, "error": "License key not found."}

            license_row = rows[0]
            if not license_row.get("is_active", True):
                return {"ok": False, "error": "License key is inactive."}

            expires_at = license_row.get("expires_at")
            if expires_at:
                expires_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if datetime.now(timezone.utc) > expires_dt:
                    return {"ok": False, "error": "License key has expired."}

            # 2. Enforce per-machine activation limit.
            mid = machine_id.get_machine_id()
            existing_resp = (
                sb.table("license_activations")
                .select("id")
                .eq("license_key", key)
                .eq("machine_id", mid)
                .execute()
            )
            is_activated_machine = bool(existing_resp.data)

            if not is_activated_machine:
                max_activations = license_row.get("max_activations") or 1
                all_resp = (
                    sb.table("license_activations")
                    .select("id")
                    .eq("license_key", key)
                    .execute()
                )
                if len(all_resp.data or []) >= max_activations:
                    return {"ok": False, "error": "Activation limit reached for this license."}

            # 3. Record / refresh activation.
            now = datetime.now(timezone.utc).isoformat()
            if is_activated_machine and existing_resp.data:
                activation_id = existing_resp.data[0]["id"]
                sb.table("license_activations").update({"last_seen_at": now}).eq("id", activation_id).execute()
            else:
                sb.table("license_activations").insert({
                    "license_key": key,
                    "machine_id": mid,
                    "activated_at": now,
                    "last_seen_at": now,
                }).execute()

            # 4. Sync activation_count on the license row for quick inspection.
            count_resp = (
                sb.table("license_activations")
                .select("id")
                .eq("license_key", key)
                .execute()
            )
            sb.table("licenses").update({"activation_count": len(count_resp.data or [])}).eq("key", key).execute()

            # 5. Cache locally so the bot can start without repeated online checks.
            LICENSE_FILE.write_text(key)
            return {"ok": True, "key": key}

        except Exception as exc:
            return {"ok": False, "error": f"Activation server error: {exc}"}

    # ── MT5 connection ────────────────────────────────────────────────────────

    def connect_mt5(self) -> dict:
        try:
            import config
            from src.data_collector import connect_mt5 as _connect_mt5
            # Path-only connection is tried first (src/data_collector.py already
            # avoids re-sending credentials to an already-logged-in terminal,
            # which can hang the IPC pipe); these are only used as a fallback,
            # e.g. on a fresh VPS where the terminal hasn't been logged in yet.
            ok = _connect_mt5(
                login=config.MT5_LOGIN or None,
                password=config.MT5_PASSWORD or None,
                server=config.MT5_SERVER or None,
                retries=2,
            )
            if not ok:
                import MetaTrader5 as mt5
                self._mt5_ok = False
                return {"ok": False, "error": str(mt5.last_error())}
            import MetaTrader5 as mt5
            info = mt5.account_info()
            self._mt5_ok = True
            self._add_log("[MT5]", "win", f"Connected · {info.server}" if info else "Connected", speaker="Boss")
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
        self._add_log("[START]", "win", "Bot started · scanning US30 for Silver Bullet setups", speaker="Boss")

    def _stop_bot(self) -> None:
        if self._bot:
            self._bot.running = False
        self._bot_running = False
        if self._log_handler:
            logging.getLogger("silver_bullet_bot").removeHandler(self._log_handler)
            self._log_handler = None
        self._add_log("[STOP]", "inf", "Bot stopped by user · positions held open", speaker="Boss")

    def _is_running(self) -> bool:
        return self._bot_running and bool(self._bot_thread and self._bot_thread.is_alive())

    def _restart_bot(self) -> None:
        """Stop the bot (waiting for its loop to actually exit, not just
        flipping the flag) and start a fresh instance so it picks up
        whatever was just saved to .env — settings like Aggressive Mode /
        Off-Hours / Skip News Days are only read once, in SilverBulletBot
        .__init__, so toggling them has no effect on an already-running
        bot until it's restarted. Joining the old thread here (unlike
        _stop_bot, which leaves it running in the background) avoids two
        overlapping bot loops / MT5 connections for the duration of a
        naive stop-then-start."""
        if self._is_running():
            if self._bot:
                self._bot.running = False
            if self._bot_thread:
                self._bot_thread.join(timeout=15)
            self._bot_running = False
            if self._log_handler:
                logging.getLogger("silver_bullet_bot").removeHandler(self._log_handler)
                self._log_handler = None
        self._add_log("[RESTART]", "sig", "Bot restarting to apply updated settings...", speaker="Boss")
        self._start_bot()

    # ── Live stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        running   = self._is_running()
        account   = self._get_account()
        positions = self._get_positions()

        balance = account["balance"] if account else 0.0
        equity  = account["equity"]  if account else 0.0
        profit  = account["profit"]  if account else 0.0

        # Up to 6 concurrent instances (3 SB symbols + 3 TL symbols) can each
        # have a position open at once — report all of them, not just one.
        open_trades = []
        try:
            import MetaTrader5 as mt5
            for pos in positions:
                breakeven_set = (
                    (pos.sl >= pos.price_open if pos.type == mt5.ORDER_TYPE_BUY else pos.sl <= pos.price_open)
                    if pos.sl != 0 else False
                )
                open_trades.append({
                    "ticket":    pos.ticket,
                    "symbol":    pos.symbol,
                    "side":      "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                    "entry":     f"{pos.price_open:,.2f}",
                    "sl":        f"{pos.sl:,.2f}" if pos.sl else "—",
                    "tp":        f"{pos.tp:,.2f}" if pos.tp else "—",
                    "float_pnl": f"+${pos.profit:.2f}" if pos.profit >= 0 else f"-${abs(pos.profit):.2f}",
                    "lots":      f"{pos.volume:.2f}",
                    "breakeven": breakeven_set,
                })
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
            NY_TZ = ZoneInfo("America/New_York")
            BW_TZ = ZoneInfo("Africa/Gaborone")
            now_ny = datetime.now(NY_TZ)
            ny_h = now_ny.hour

            def _ny_label_to_botswana(hh_mm: str) -> str:
                # Windows are authored as NY-local "HH:MM" (see
                # silver_bullet/config.py). Convert via a real tz-aware
                # datetime rather than a fixed offset so the US/Botswana gap
                # (6h during EDT, 7h during EST) is always correct.
                h, m = map(int, hh_mm.split(":"))
                ny_dt = now_ny.replace(hour=h, minute=m, second=0, microsecond=0)
                return ny_dt.astimezone(BW_TZ).strftime("%H:%M")

            session = "Off-Hours"
            for start_s, end_s in cfg.windows:
                sh, sm = map(int, start_s.split(":"))
                eh, em = map(int, end_s.split(":"))
                start_h = sh + sm / 60.0
                end_h = eh + em / 60.0
                if start_h <= ny_h < end_h:
                    bw_start = _ny_label_to_botswana(start_s)
                    bw_end = _ny_label_to_botswana(end_s)
                    session = f"{bw_start}–{bw_end} BWT (Active)"
                    break
            if session == "Off-Hours" and _cfg.SB_OFF_HOURS and ny_h < 17:
                bw_close = _ny_label_to_botswana(cfg.off_hours_close_time)
                session = f"Off-Hours (Active until {bw_close} BWT)"
            # Surface news pause in the dashboard so it is obvious why the bot is idle.
            if _cfg.SB_NEWS:
                from silver_bullet.news_calendar import is_news_day
                if is_news_day(now_ny.date()):
                    session += " · News pause"
        except Exception:
            session = "--"

        import config as _cfg
        import MetaTrader5 as mt5
        from multi_symbol_targets import MB_TARGETS, SB_TARGETS, TL_TARGETS

        # One reading per configured instance (a symbol traded by several
        # strategies, e.g. DE30m or USDJPYm, appears once per strategy — each
        # has its own independent adapter/position/risk on it).
        active_symbols = []
        any_market_open = False
        mb_targets = MB_TARGETS if getattr(_cfg, "MB_ENABLED", False) else {}
        for strategy, targets in (("SB", SB_TARGETS), ("TL", TL_TARGETS), ("MB", mb_targets)):
            for symbol in targets:
                entry = {"symbol": symbol, "strategy": strategy, "price": None, "market_open": False}
                if self._mt5_ok:
                    tick = mt5.symbol_info_tick(symbol)
                    sym = mt5.symbol_info(symbol)
                    if tick is not None and sym is not None and sym.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
                        last_tick = datetime.fromtimestamp(tick.time, tz=timezone.utc)
                        is_open = (datetime.now(tz=timezone.utc) - last_tick).total_seconds() < 300
                        entry["market_open"] = is_open
                        entry["price"] = f"{tick.bid:,.2f}"
                        any_market_open = any_market_open or is_open
                active_symbols.append(entry)

        return {
            "running":        running,
            "connected":      self._mt5_ok,
            "balance":        f"${balance:,.2f}" if account else "--",
            "equity":         f"${equity:,.2f}"  if account else "--",
            "profit":         (f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}") if account else "--",
            "open_trades":    str(len(positions)),
            "open_positions": open_trades,
            "next_refresh":   next_refresh,
            "session":        session,
            "daily_cap_used": "--",
            "active_symbols": active_symbols,
            "risk_pct":       str(_cfg.SB_RISK_PCT),
            "max_trades":     str(_cfg.SB_MAX_TRADES_PER_DAY),
            "timeframe":      "M5",
            "market_open":    any_market_open,
        }

    # ── Market snapshot (dashboard heatmap) ─────────────────────────────────────

    def _get_symbol_reading(self, symbol: str, label: str) -> dict:
        empty = {"label": label, "price": None, "change_pct": None}
        if not self._mt5_ok or not symbol:
            return empty
        try:
            import MetaTrader5 as mt5
            if not mt5.symbol_select(symbol, True):
                return empty
            tick = mt5.symbol_info_tick(symbol)
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_D1, 0, 1)
            if tick is None or rates is None or len(rates) == 0:
                return empty
            day_open = float(rates[0]["open"])
            price = float(tick.bid)
            change_pct = round((price - day_open) / day_open * 100, 2) if day_open else None
            return {"label": label, "price": f"{price:,.2f}", "change_pct": change_pct}
        except Exception:
            return empty

    def get_market_snapshot(self) -> list:
        from multi_symbol_targets import SB_TARGETS, TL_TARGETS
        # Unique symbols across both strategies' top-3 targets — a symbol
        # traded by both (e.g. DE30m) gets one heatmap tile, not two.
        symbols = list(dict.fromkeys(list(SB_TARGETS) + list(TL_TARGETS)))
        return [self._get_symbol_reading(sym, sym) for sym in symbols]

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
            from trendline.live_adapter import TL_MAGIC
            from mutanabby.live_adapter import MB_MAGIC
            magics = (SB_MAGIC, TL_MAGIC, MB_MAGIC)
            return [p for p in (mt5.positions_get() or []) if p.magic in magics]
        except Exception:
            return []

    # ── Log ──────────────────────────────────────────────────────────────────

    def get_log(self) -> list:
        with self._lock:
            return list(reversed(self._log_buffer[-40:]))

    def _add_log(self, tag: str, kind: str, text: str, speaker: str = "Scanner") -> None:
        t = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._log_buffer.append({"t": t, "tag": tag, "k": kind, "x": text, "speaker": speaker})
            if len(self._log_buffer) > 200:
                self._log_buffer = self._log_buffer[-200:]

    # ── Trade history ─────────────────────────────────────────────────────────

    def get_trades(self) -> list:
        if not self._mt5_ok:
            return []
        try:
            import MetaTrader5 as mt5
            from silver_bullet.live_adapter import SB_MAGIC
            from trendline.live_adapter import TL_MAGIC
            from mutanabby.live_adapter import MB_MAGIC
            from src.ticket_store import load_tickets
            magics = (SB_MAGIC, TL_MAGIC, MB_MAGIC)
            from_dt = datetime.now() - timedelta(days=30)
            # Some broker trade servers (e.g. AtlasFunded-Server) timestamp
            # deals several hours ahead of true UTC. Padding the upper bound
            # keeps very recent trades from looking like they're "in the
            # future" and getting excluded from the range query.
            to_dt = datetime.now() + timedelta(hours=6)
            deals = mt5.history_deals_get(from_dt, to_dt) or []

            # Some brokers (e.g. AtlasFunded-Server) zero out `magic` on
            # deals regardless of what the order set, so magic alone can't
            # be trusted to identify this bot's trades. Fall back to the
            # locally recorded ticket numbers the bot confirmed opening.
            known_tickets = load_tickets()

            opens, closes = {}, []
            for d in deals:
                if d.magic not in magics and d.position_id not in known_tickets:
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
                    "symbol":   c.symbol,
                    "side":     side,
                    "lots":     f"{c.volume:.2f}",
                    "entry":    f"{o.price:,.2f}",
                    "exit":     f"{c.price:,.2f}",
                    "pips":     f"{'+' if pts >= 0 else ''}{pts:.0f}",
                    "pnl":      round(pnl, 2),
                    "win":      pnl > 0,
                    "pnl_text": f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}",
                })
            self._grade_new_trades(rows)
            return rows
        except Exception:
            return []

    def _grade_new_trades(self, rows: list) -> None:
        """Have Grader call out newly-closed trades in the activity feed.

        get_trades() re-derives the full 30-day history from MT5 on every
        poll, so "new" means "not graded yet this process" — the first call
        after a (re)start just seeds the seen-set instead of replaying the
        whole history as if it just happened.
        """
        ids = {r["id"] for r in rows}
        if not self._graded_seeded:
            self._graded_ids |= ids
            self._graded_seeded = True
            return
        new_ids = ids - self._graded_ids
        if not new_ids:
            return
        today = datetime.now().strftime("%b %d")
        for r in rows:
            if r["id"] not in new_ids:
                continue
            self._graded_ids.add(r["id"])
            wins   = sum(1 for x in rows if x["win"]     and x["date"] == today)
            losses = sum(1 for x in rows if not x["win"] and x["date"] == today)
            outcome = "Win" if r["win"] else "Loss"
            self._add_log(
                "[GRADE]", "win" if r["win"] else "warn",
                f"{outcome} on {r['side']} {r['id']} · {r['pnl_text']} ({r['pips']} pts). "
                f"Today: {wins}W / {losses}L",
                speaker="Grader",
            )

    # ── Economic calendar ───────────────────────────────────────────────────────

    def get_calendar(self, count: int = 8) -> list:
        import config
        from silver_bullet.news_calendar import HIGH_IMPACT_DATES, event_label

        today = datetime.now().date()
        upcoming = sorted(
            d for d in (datetime.strptime(s, "%Y-%m-%d").date() for s in HIGH_IMPACT_DATES)
            if d >= today
        )[:count]

        rows = []
        for d in upcoming:
            delta = (d - today).days
            detail = "today · high impact" if delta == 0 else f"in {delta} day{'s' if delta != 1 else ''} · high impact"
            # Only claim the bot will pause entries when the "Skip News Days"
            # setting (SB_NEWS) is actually on — otherwise this text lies to
            # the user about live bot behavior.
            if config.SB_NEWS:
                detail += "\nBot pauses new entries on this date."
            rows.append({
                "day":     d.day,
                "weekday": d.strftime("%b").upper(),
                "month":   d.strftime("%b").upper(),
                "title":   event_label(d),
                "tag":     "NEWS DAY",
                "tagColor": "#EF4444",
                "detail":  detail,
            })
        return rows

    # ── Settings ──────────────────────────────────────────────────────────────

    def get_settings(self) -> dict:
        import config
        from multi_symbol_targets import SB_TARGETS, TL_TARGETS
        return {
            "login":                str(config.MT5_LOGIN),
            "server":               config.MT5_SERVER,
            # Read-only: trading symbols come from multi_symbol_targets.py
            # (top-3 per strategy by backtested profit factor), not a single
            # user-editable field — there's no one "the symbol" anymore.
            "sb_symbols":           list(SB_TARGETS),
            "tl_symbols":           list(TL_TARGETS),
            "risk_pct":             str(config.SB_RISK_PCT),
            "daily_loss_limit_usd": str(config.SB_DAILY_LOSS_LIMIT_USD),
            "max_trades_per_day":   str(config.SB_MAX_TRADES_PER_DAY),
            "max_drawdown_pct":     str(config.SB_MAX_DRAWDOWN_PCT),
            "aggressive":           config.SB_AGGRESSIVE,
            "off_hours":            config.SB_OFF_HOURS,
            "news":                 config.SB_NEWS,
        }

    def save_settings(self, data: dict) -> dict:
        try:
            import config

            mapping = {
                "login":                "MT5_LOGIN",
                "server":               "MT5_SERVER",
                "risk_pct":             "SB_RISK_PCT",
                "daily_loss_limit_usd": "SB_DAILY_LOSS_LIMIT_USD",
                "max_trades_per_day":   "SB_MAX_TRADES_PER_DAY",
                "max_drawdown_pct":     "SB_MAX_DRAWDOWN_PCT",
                "aggressive":           "SB_AGGRESSIVE",
                "off_hours":            "SB_OFF_HOURS",
                "news":                 "SB_NEWS",
            }

            updates: dict[str, str] = {}
            for field, env_key in mapping.items():
                if field in data:
                    val = data[field]
                    updates[env_key] = str(val).lower() if isinstance(val, bool) else str(val)

            # Password is write-only: an empty value means "leave it alone" so
            # the UI never has to display or round-trip the current secret.
            password = data.get("password", "")
            if password:
                updates["MT5_PASSWORD"] = password

            # Shared, non-destructive rewrite: preserves comments/blank lines/
            # ordering and any untouched key (e.g. MT5_PATH).
            paths.update_env_file(config.ENV_PATH, updates)

            # Reload config so next get_settings() call reflects the saved values
            import importlib, config as cfg
            importlib.reload(cfg)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
