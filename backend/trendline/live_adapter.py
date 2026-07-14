"""
Trendline live adapter: connects the trendline signal engine to MT5.

On each call to .cycle(symbol):
  1. Fetch the last cfg.bars_lookback completed H1 bars from MT5
  2. Feed any unprocessed bars through SignalGenerator
  3. On a new Signal: place a market order in MT5 with SL and TP pre-set
     (v1 is aggressive-entry-only — no pending/limit-order path)
  4. Monitor fill: MT5 manages SL/TP automatically once the position is open
  5. Breakeven + trailing stop once price moves in our favour

Design notes
------------
- Mirrors silver_bullet/live_adapter.py's structure and idioms, trimmed to
  v1 needs: no session windows, no off-hours variant, no pending-order path.
  silver_bullet/*.py is not modified by this module.
- bar_idx is always the index in the CURRENT cycle's array — the
  SignalGenerator only carries trendline/trade-active state across calls,
  not price data, so this is safe (same discipline as Silver Bullet's adapter).
- Magic number 202411001 is reserved for the Trendline strategy (distinct
  from Silver Bullet's SB_MAGIC = 202406122).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import pandas as pd

import config as root_config

from src.ticket_store import record_ticket

from .config import TrendlineConfig
from .strategy import Signal, SignalGenerator

NY_TZ = ZoneInfo("America/New_York")
TL_MAGIC = 202411001


class TrendlineLiveAdapter:
    """Stateful, bar-by-bar adapter. Instantiate once; call .cycle() every 5s."""

    def __init__(self, cfg: TrendlineConfig, symbol: Optional[str] = None):
        self._cfg = cfg
        self._generator = SignalGenerator(cfg)
        self._symbol: Optional[str] = symbol
        self._last_bar_time: Optional[pd.Timestamp] = None
        self._open_ticket: Optional[int] = None
        self._open_signal: Optional[Signal] = None
        self._open_fill_price: Optional[float] = None
        self._initialized: bool = False
        # Breakeven / trailing stop tracking for the open position
        self._breakeven_triggered: bool = False
        self._trail_best_price: Optional[float] = None
        # News-day tracking (to log once per day)
        self._news_skip_date: str = ""
        # Drawdown circuit breaker
        self._drawdown_floor: Optional[float] = None
        self._drawdown_halted: bool = False
        # Daily limit tracking (NY date)
        self._daily_limit_date: str = ""
        self._daily_loss_usd: float = 0.0
        self._daily_trades: int = 0
        self._daily_limit_halted: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cycle(self, symbol: str) -> None:
        """Called from the main bot loop. Manages the full lifecycle of one
        trendline setup."""
        from src.logger import logger

        logger.info(
            f"[TL] Cycle start | symbol={symbol} | initialized={self._initialized} | "
            f"open={self._open_ticket}"
        )

        if not self._validate_symbol(symbol):
            logger.info("[TL] Cycle aborted | symbol validation failed")
            return

        if self._drawdown_halted:
            logger.info("[TL] Cycle skipped | drawdown circuit breaker active")
            return
        if not self._check_drawdown_floor(symbol):
            logger.info("[TL] Cycle skipped | drawdown floor breached")
            return
        if not self._check_daily_limits(symbol):
            logger.info("[TL] Cycle skipped | daily limit reached")
            return

        bars = self._fetch_bars(symbol, n=self._cfg.bars_lookback)
        if bars is None or len(bars) < 10:
            if not self._market_is_open(symbol):
                logger.info(f"[TL] Market closed for {symbol} — waiting for reopen")
            else:
                logger.warning(f"[TL] Bar fetch failed for {symbol}")
            return

        # Drop the currently-forming (incomplete) bar
        completed = bars.iloc[:-1]
        if completed.empty:
            logger.info("[TL] Cycle skipped | no completed bars available")
            return

        logger.info(
            f"[TL] Bars fetched | total={len(bars)} completed={len(completed)} | "
            f"first={completed.index[0]} UTC | last={completed.index[-1]} UTC"
        )

        times  = completed.index.tolist()
        highs  = completed["high"].to_numpy(dtype=float)
        lows   = completed["low"].to_numpy(dtype=float)
        closes = completed["close"].to_numpy(dtype=float)
        opens  = completed["open"].to_numpy(dtype=float)

        # 1. Detect if the open position was closed externally (SL/TP hit)
        self._sync_position(symbol)

        # 2. Manage open position (breakeven/trail) and return — no new
        #    scanning while a position is open (one_trade_at_a_time).
        if self._open_ticket is not None:
            positions = mt5.positions_get(ticket=self._open_ticket) or []
            if positions:
                pos  = positions[0]
                side = "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT"
                logger.info(
                    f"[TL] Position status | #{pos.ticket} | {side} | "
                    f"Price={pos.price_current:.5f} | P&L=${pos.profit:+.2f}"
                )
            self._check_breakeven(symbol)
            logger.info("[TL] Cycle end | open position management complete")
            return

        today_ny = datetime.now(NY_TZ).date().isoformat()

        # News-day circuit breaker: no new entries on high-impact macro days.
        from silver_bullet.news_calendar import is_news_day
        if self._cfg.skip_news_days and is_news_day(today_ny):
            if self._news_skip_date != today_ny:
                logger.info(f"[TL] News day {today_ny} — trading paused for high-impact macro releases")
                self._news_skip_date = today_ny
            return

        # 3. Feed unprocessed bars through the signal generator
        latest_idx = len(times) - 1
        processed_count = 0
        signal_count = 0
        for i, ts in enumerate(times):
            if self._last_bar_time is not None and ts <= self._last_bar_time:
                continue
            processed_count += 1

            ts_ny = ts.astimezone(NY_TZ)
            date_str = ts_ny.date().isoformat()

            signal = self._generator.on_bar(
                bar_idx=i, highs=highs, lows=lows, closes=closes, opens=opens,
                date_str=date_str,
            )

            if signal is not None:
                signal_count += 1

            # Act on today's signals only. On the very first cycle, only
            # trade the most recent completed bar so we don't fire on stale
            # history built up while warming the generator's state.
            if signal is not None and date_str == today_ny:
                if not self._initialized and i != latest_idx:
                    logger.info(
                        f"[TL] Signal skipped | init warmup | bar={i} latest={latest_idx}"
                    )
                    continue
                lots = self._compute_lots(symbol, signal)
                if lots is not None:
                    self._place_market(symbol, signal, lots)
                break  # one market order per cycle
            elif signal is not None:
                logger.info(
                    f"[TL] Signal skipped | init={self._initialized} | "
                    f"date={date_str} today={today_ny}"
                )

        logger.info(
            f"[TL] Signal scan complete | processed={processed_count} | "
            f"signals_found={signal_count}"
        )

        if times:
            self._last_bar_time = times[-1]
        self._initialized = True
        logger.info("[TL] Cycle end | watermark advanced | init=True")

    def shutdown(self, symbol: str) -> None:
        """Close any open position on shutdown."""
        if self._open_ticket is not None:
            self._time_exit(symbol)

    # ------------------------------------------------------------------
    # MT5 operations
    # ------------------------------------------------------------------

    def _fetch_bars(self, symbol: str, n: int) -> Optional[pd.DataFrame]:
        if not mt5.symbol_info(symbol):
            mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[["open", "high", "low", "close"]]

    def _market_is_open(self, symbol: str) -> bool:
        """Best-effort check whether the symbol is currently tradeable."""
        from datetime import timezone

        tick = mt5.symbol_info_tick(symbol)
        sym = mt5.symbol_info(symbol)
        if tick is None or sym is None:
            return False
        if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            return False
        last_tick = datetime.fromtimestamp(tick.time, tz=timezone.utc)
        age_sec = (datetime.now(tz=timezone.utc) - last_tick).total_seconds()
        return age_sec < 300  # 5 minutes

    def _sync_position(self, symbol: str) -> None:
        """Clear open_ticket when MT5 closes the position via SL or TP, and
        notify the generator so the one-trade-at-a-time gate lifts."""
        if self._open_ticket is None:
            return
        positions = mt5.positions_get(ticket=self._open_ticket) or []
        if not positions:
            from src.logger import logger
            logger.info(f"[TL] Position #{self._open_ticket} closed by MT5 (SL/TP)")
            self._open_ticket         = None
            self._open_signal         = None
            self._open_fill_price     = None
            self._breakeven_triggered = False
            self._trail_best_price    = None
            self._generator.notify_trade_closed()

    def _check_breakeven(self, symbol: str) -> None:
        """Move stop to entry at breakeven_r; then trail at trail_r beyond that."""
        if self._open_signal is None or self._open_fill_price is None:
            return

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return

        from src.logger import logger

        cfg      = self._cfg
        sig      = self._open_signal
        fill     = self._open_fill_price
        risk_pts = abs(fill - sig.stop_price)
        is_long  = sig.direction == "long"
        current_px = tick.bid if is_long else tick.ask

        # Phase 1 — breakeven
        if not self._breakeven_triggered and cfg.breakeven_r > 0:
            trigger_dist = risk_pts * cfg.breakeven_r
            triggered = (
                current_px >= fill + trigger_dist if is_long
                else current_px <= fill - trigger_dist
            )
            if triggered:
                positions = mt5.positions_get(ticket=self._open_ticket) or []
                if not positions:
                    return
                pos      = positions[0]
                sym_info = mt5.symbol_info(symbol)
                d        = sym_info.digits if sym_info else 5
                result   = mt5.order_send({
                    "action":   mt5.TRADE_ACTION_SLTP,
                    "symbol":   symbol,
                    "position": pos.ticket,
                    "sl":       round(fill, d),
                    "tp":       round(pos.tp, d),
                })
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self._breakeven_triggered = True
                    logger.info(
                        f"[TL] Breakeven triggered | #{pos.ticket} | SL moved to {fill:.5f}"
                    )

        # Phase 2 — trailing stop (only after breakeven)
        if self._breakeven_triggered and cfg.trail_r > 0:
            if is_long:
                if self._trail_best_price is None or current_px > self._trail_best_price:
                    self._trail_best_price = current_px
                new_sl = self._trail_best_price - risk_pts * cfg.trail_r
            else:
                if self._trail_best_price is None or current_px < self._trail_best_price:
                    self._trail_best_price = current_px
                new_sl = self._trail_best_price + risk_pts * cfg.trail_r

            positions = mt5.positions_get(ticket=self._open_ticket) or []
            if not positions:
                return
            pos      = positions[0]
            sym_info = mt5.symbol_info(symbol)
            d        = sym_info.digits if sym_info else 5
            current_sl = pos.sl

            sl_improves = (new_sl > current_sl) if is_long else (new_sl < current_sl)
            if sl_improves:
                result = mt5.order_send({
                    "action":   mt5.TRADE_ACTION_SLTP,
                    "symbol":   symbol,
                    "position": pos.ticket,
                    "sl":       round(new_sl, d),
                    "tp":       round(pos.tp, d),
                })
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(
                        f"[TL] Trail stop updated | #{pos.ticket} | SL moved to {new_sl:.5f}"
                    )

    def _place_market(self, symbol: str, signal: Signal, lots: float) -> None:
        from src.logger import logger

        if not self._validate_symbol(symbol):
            return

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[TL] Symbol {symbol} not found")
            return
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"[TL] No tick data for {symbol}")
            return

        is_long    = signal.direction == "long"
        order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL

        price = tick.ask if is_long else tick.bid
        stop_price = tick.bid if is_long else tick.ask
        d = sym_info.digits

        # Skip stale signals. If price has already moved past the signal
        # entry by more than half the original risk, the setup is gone and
        # adjusting stops would create a bad R:R trade. The signal is priced
        # off a bar CLOSE, so this matters even more here than for a
        # tick-reactive strategy — the adapter only reacts within its ~5s
        # loop cadence after that bar has already completed.
        risk_pts = abs(signal.entry_price - signal.stop_price)
        entry_slip = abs(price - signal.entry_price)
        if entry_slip > risk_pts * 0.5:
            logger.info(
                f"[TL] Signal stale | Price={price:.5f} Entry={signal.entry_price:.5f} "
                f"slip={entry_slip:.5f} (risk={risk_pts:.5f}) — skipping market entry"
            )
            return

        # Enforce broker minimum stop distance from the relevant market price.
        min_dist = sym_info.trade_stops_level * sym_info.point
        sl = signal.stop_price
        tp = signal.target_price
        if is_long:
            if stop_price - sl < min_dist:
                sl = round(stop_price - min_dist * 1.1, d)
            if tp - stop_price < min_dist:
                tp = round(stop_price + min_dist * 1.1, d)
        else:
            if sl - stop_price < min_dist:
                sl = round(stop_price + min_dist * 1.1, d)
            if stop_price - tp < min_dist:
                tp = round(stop_price - min_dist * 1.1, d)

        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       lots,
            "type":         order_type,
            "price":        round(price, d),
            "sl":           round(sl, d),
            "tp":           round(tp, d),
            "deviation":    20,
            "magic":        TL_MAGIC,
            "comment":      "Trendline_MKT",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            positions = mt5.positions_get(ticket=result.order) or []
            fill_price = positions[0].price_open if positions else price
            self._open_ticket         = result.order
            self._open_fill_price     = fill_price
            self._open_signal         = signal
            self._breakeven_triggered = False
            self._trail_best_price    = None
            self._generator.notify_trade_opened()
            record_ticket(result.order)
            logger.info(
                f"[TL] MARKET {signal.direction.upper()} | {symbol} | "
                f"Lots={lots:.2f} | Fill={fill_price:.5f} "
                f"SL={sl:.5f} TP={tp:.5f} | pattern={signal.pattern} | #{result.order}"
            )
        else:
            logger.error(
                f"[TL] Market order failed | code={result.retcode} | {result.comment}"
            )

    def _time_exit(self, symbol: str) -> None:
        if self._open_ticket is None:
            return
        from src.logger import logger

        positions = mt5.positions_get(ticket=self._open_ticket) or []
        if not positions:
            self._open_ticket = None
            self._generator.notify_trade_closed()
            return

        pos  = positions[0]
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return

        is_buy      = pos.type == mt5.ORDER_TYPE_BUY
        close_price = tick.bid if is_buy else tick.ask
        close_type  = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY

        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         close_type,
            "position":     pos.ticket,
            "price":        close_price,
            "deviation":    20,
            "magic":        TL_MAGIC,
            "comment":      "TL_shutdown_exit",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[TL] Shutdown exit | #{pos.ticket} | PnL ${pos.profit:.2f}")
            self._open_ticket         = None
            self._open_signal         = None
            self._open_fill_price     = None
            self._breakeven_triggered = False
            self._trail_best_price    = None
            self._generator.notify_trade_closed()
        else:
            logger.error(
                f"[TL] Shutdown exit failed | code={result.retcode} | {result.comment}"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_symbol(self, symbol: str) -> bool:
        """Guard against trading the wrong instrument."""
        from src.logger import logger

        if not symbol:
            logger.error("[TL] No symbol provided to adapter cycle — skipping")
            return False

        if self._symbol is not None and symbol != self._symbol:
            logger.error(
                f"[TL] Symbol mismatch | expected={self._symbol} received={symbol}. "
                f"Skipping cycle to avoid wrong-instrument execution."
            )
            return False

        return True

    def _compute_lots(self, symbol: str, signal: Signal) -> Optional[float]:
        from src.logger import logger

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[TL] No symbol info for {symbol}")
            return None

        account = mt5.account_info()
        if account is None:
            return None

        usable_capital = min(account.balance, account.equity)
        if usable_capital <= 0:
            logger.error("[TL] Account balance/equity is zero or negative — cannot size position")
            return None

        min_balance = getattr(root_config, "TL_MIN_BALANCE", 15.0)
        if usable_capital < min_balance:
            logger.warning(
                f"[TL] Usable capital ${usable_capital:.2f} is below the "
                f"configured minimum ${min_balance:.2f} — skipping trade"
            )
            return None

        risk_pct = max(0.01, min(float(getattr(root_config, "TL_RISK_PCT", 1.0)), 100.0))
        if usable_capital < 200.0:
            risk_pct = min(risk_pct, 2.0)

        risk_usd = usable_capital * (risk_pct / 100.0)

        small_acct_threshold = getattr(root_config, "TL_SMALL_ACCT_THRESHOLD", 150.0)
        max_risk_usd = getattr(root_config, "TL_MAX_RISK_USD", 1.0)
        if usable_capital < small_acct_threshold:
            capped_risk_usd = min(risk_usd, max_risk_usd)
            if capped_risk_usd < risk_usd:
                logger.info(
                    f"[TL] Small-account cap | Risk reduced from ${risk_usd:.2f} "
                    f"to ${capped_risk_usd:.2f} (balance below ${small_acct_threshold:.0f})"
                )
            risk_usd = capped_risk_usd

        risk_pts = abs(signal.entry_price - signal.stop_price)
        tick_val = sym_info.trade_tick_value
        tick_size = sym_info.trade_tick_size

        if risk_pts <= 0 or tick_val <= 0 or tick_size <= 0:
            logger.warning(
                f"[TL] Invalid sizing inputs: risk_pts={risk_pts}, "
                f"tick_val={tick_val}, tick_size={tick_size} — using volume_min"
            )
            return sym_info.volume_min

        value_per_pt = tick_val / tick_size
        raw = risk_usd / (risk_pts * value_per_pt)
        step = sym_info.volume_step
        lots = round(raw / step) * step
        lots = max(sym_info.volume_min, min(lots, sym_info.volume_max, 8.0))

        actual_risk_usd = lots * risk_pts * value_per_pt
        if actual_risk_usd > usable_capital * 0.05:
            logger.warning(
                f"[TL] Sizing overshoot: {lots} lots would risk "
                f"${actual_risk_usd:.2f} ({actual_risk_usd / usable_capital * 100:.1f}% "
                f"of capital). Skipping trade."
            )
            return None

        logger.info(
            f"[TL] Sizing | Capital=${usable_capital:.2f} RiskPct={risk_pct:.2f}% "
            f"Risk=${risk_usd:.2f} SL={risk_pts:.5f} RawLots={raw:.3f} "
            f"FinalLots={lots:.2f} TickVal={tick_val:.5f}/TickSize={tick_size}"
        )
        return round(lots, 2)

    def _check_daily_limits(self, symbol: str) -> bool:
        """Return True if new trades are allowed today.

        Enforces TL_DAILY_LOSS_LIMIT_USD and TL_MAX_TRADES_PER_DAY by
        querying MT5 history for today's closed Trendline deals. Resets at
        the start of each NY trading day (same convention as Silver Bullet,
        for a consistent "day" definition across strategies/dashboard)."""
        from datetime import timezone, timedelta
        from src.logger import logger

        today_ny = datetime.now(NY_TZ).date().isoformat()

        if today_ny != self._daily_limit_date:
            self._daily_limit_date = today_ny
            self._daily_loss_usd = 0.0
            self._daily_trades = 0
            self._daily_limit_halted = False
            logger.info(f"[TL] Daily limits reset for {today_ny}")

        if self._daily_limit_halted:
            return False

        ny_midnight = datetime.now(NY_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        from_date = ny_midnight.astimezone(timezone.utc)
        to_date = datetime.now(timezone.utc) + timedelta(hours=6)

        try:
            deals = mt5.history_deals_get(from_date, to_date) or []
        except Exception as exc:
            logger.warning(f"[TL] Failed to fetch history deals: {exc}")
            deals = []

        daily_pnl = 0.0
        daily_entries = 0
        for deal in deals:
            if deal.magic != TL_MAGIC:
                continue
            if deal.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                daily_pnl += deal.profit + deal.commission + deal.swap
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    daily_entries += 1

        self._daily_loss_usd = daily_pnl
        self._daily_trades = daily_entries

        loss_limit = getattr(root_config, "TL_DAILY_LOSS_LIMIT_USD", 10.0)
        max_trades = getattr(root_config, "TL_MAX_TRADES_PER_DAY", 3)

        if daily_pnl <= -abs(loss_limit):
            logger.warning(
                f"[TL] Daily loss limit reached | PnL ${daily_pnl:.2f} <= -${loss_limit:.2f}. "
                f"No new trades today."
            )
            self._daily_limit_halted = True
            return False

        if daily_entries >= max_trades:
            logger.info(
                f"[TL] Daily trade cap reached | {daily_entries}/{max_trades} trades. "
                f"No new trades today."
            )
            self._daily_limit_halted = True
            return False

        return True

    def _check_drawdown_floor(self, symbol: str) -> bool:
        """Return True if trading is allowed; halt and flatten if floor is breached."""
        from src.logger import logger

        if self._drawdown_halted:
            return False

        account = mt5.account_info()
        if account is None:
            return False

        usable_capital = min(account.balance, account.equity)
        if usable_capital <= 0:
            return False

        if self._drawdown_floor is None:
            drawdown_pct = max(0.0, min(float(getattr(root_config, "TL_MAX_DRAWDOWN_PCT", 50.0)), 100.0))
            self._drawdown_floor = usable_capital * (1.0 - drawdown_pct / 100.0)
            logger.info(
                f"[TL] Drawdown floor set | Start=${usable_capital:.2f} "
                f"Floor=${self._drawdown_floor:.2f} (max {drawdown_pct:.1f}% loss)"
            )

        if usable_capital <= self._drawdown_floor:
            logger.warning(
                f"[TL] CIRCUIT BREAKER | Capital ${usable_capital:.2f} hit floor "
                f"${self._drawdown_floor:.2f}. Halting all trading and flattening."
            )
            self._drawdown_halted = True
            if self._open_ticket is not None:
                self._time_exit(symbol)
            return False

        return True
