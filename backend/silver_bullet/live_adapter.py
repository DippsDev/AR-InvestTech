"""
Silver Bullet live adapter: connects the backtester signal engine to MT5.

On each call to .cycle(symbol):
  1. Fetch the last 150 completed M5 bars from MT5
  2. Feed any unprocessed bars through SignalGenerator (same engine as the backtest)
  3. On a new Signal: place a Buy/Sell Limit pending order in MT5 with SL and TP pre-set
  4. Monitor fill: MT5 manages SL/TP automatically once the limit is filled
  5. On window end: cancel unfilled pending order; close open trade at market (time exit)

Design notes
------------
- bar_idx is always the index in the CURRENT cycle's array, not a global counter.
  The SignalGenerator is stateless w.r.t. price arrays; it only carries session bias
  (a price level) across calls, so this is safe.
- Cycle 1 is an initialisation pass: historical bars feed the signal generator to
  build up session state.  On the first cycle we only act on the most recent completed
  bar, so we never fire on a signal that fired 30-40 minutes before the bot started.
- Magic number 202406122 is reserved for the Silver Bullet strategy.
"""
from __future__ import annotations

from dataclasses import replace as _dc_replace
from datetime import datetime, time as dtime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import pandas as pd

import config as root_config

from src.ticket_store import record_ticket

from .config import SilverBulletConfig
from .news_calendar import is_news_day
from .strategy import Signal, SignalGenerator

NY_TZ = ZoneInfo("America/New_York")
SB_MAGIC = 202406122


class SilverBulletLiveAdapter:
    """Stateful, bar-by-bar adapter.  Instantiate once; call .cycle() every 30 s."""

    def __init__(self, cfg: SilverBulletConfig, symbol: Optional[str] = None):
        self._cfg = cfg
        self._generator = SignalGenerator(cfg)
        # Symbol we are allowed to trade.  All MT5 operations are guarded against
        # this to prevent cross-instrument execution.
        self._symbol: Optional[str] = symbol
        self._last_bar_time: Optional[pd.Timestamp] = None  # last processed bar timestamp
        self._pending_ticket: Optional[int] = None           # MT5 pending order ticket
        self._open_ticket: Optional[int] = None              # MT5 position ticket after fill
        self._initialized: bool = False                      # False on very first cycle
        # Breakeven / trailing stop tracking for the open position
        self._open_signal: Optional[Signal] = None
        self._open_fill_price: Optional[float] = None
        self._breakeven_triggered: bool = False
        self._trail_best_price: Optional[float] = None
        # Off-hours tracking
        self._pending_is_off_hours: bool = False
        self._open_is_off_hours: bool = False
        self._off_hours_fills: int = 0
        self._off_hours_date: str = ""
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
        """Called from the main bot loop.  Manages the full lifecycle of one SB setup."""
        from src.logger import logger

        logger.info(
            f"[SB] Cycle start | symbol={symbol} | initialized={self._initialized} | "
            f"pending={self._pending_ticket} | open={self._open_ticket}"
        )

        if not self._validate_symbol(symbol):
            logger.info("[SB] Cycle aborted | symbol validation failed")
            return

        # Circuit breaker: halt if drawdown exceeds configured limit.
        if self._drawdown_halted:
            logger.info("[SB] Cycle skipped | drawdown circuit breaker active")
            return
        if not self._check_drawdown_floor(symbol):
            logger.info("[SB] Cycle skipped | drawdown floor breached")
            return
        if not self._check_daily_limits(symbol):
            logger.info("[SB] Cycle skipped | daily limit reached")
            return

        bars = self._fetch_bars(symbol, n=150)
        if bars is None or len(bars) < 10:
            if not self._market_is_open(symbol):
                logger.info(f"[SB] Market closed for {symbol} — waiting for reopen")
            else:
                logger.warning(f"[SB] Bar fetch failed for {symbol}")
            return

        # Drop the currently-forming (incomplete) bar
        completed = bars.iloc[:-1]
        if completed.empty:
            logger.info("[SB] Cycle skipped | no completed bars available")
            return

        logger.info(
            f"[SB] Bars fetched | total={len(bars)} completed={len(completed)} | "
            f"first={completed.index[0]} UTC | last={completed.index[-1]} UTC"
        )

        times  = completed.index.tolist()          # list of tz-aware UTC pd.Timestamps
        highs  = completed["high"].to_numpy(dtype=float)
        lows   = completed["low"].to_numpy(dtype=float)
        closes = completed["close"].to_numpy(dtype=float)
        opens  = completed["open"].to_numpy(dtype=float)

        # 1. Check if pending order was filled by MT5
        logger.info(
            f"[SB] Syncing fill status | pending={self._pending_ticket} | open={self._open_ticket}"
        )
        self._sync_fill_status(symbol)
        logger.info(
            f"[SB] Fill status synced | pending={self._pending_ticket} | open={self._open_ticket}"
        )

        # 2. Determine session context
        last_ny = times[-1].astimezone(NY_TZ)
        in_window, _ = self._window_at(last_ny)
        past_cutoff  = self._is_cutoff(last_ny)
        in_off_hours = self._cfg.off_hours_trading and not in_window and not past_cutoff
        window_desc = self._window_status_desc(last_ny)
        logger.info(
            f"[SB] Session context | last_bar={last_ny.strftime('%H:%M')} NY | price={closes[-1]:.2f} | "
            f"in_window={in_window} | off_hours={in_off_hours} | past_cutoff={past_cutoff} | "
            f"{window_desc} | Today: {self._daily_trades} trades, PnL ${self._daily_loss_usd:+.2f}"
        )

        # Reset daily off-hours fill counter at day change
        today_ny = datetime.now(NY_TZ).date().isoformat()
        if today_ny != self._off_hours_date:
            self._off_hours_date  = today_ny
            self._off_hours_fills = 0

        # News-day circuit breaker: no new entries on high-impact macro days.
        news_skip = self._cfg.skip_news_days and is_news_day(today_ny)
        if news_skip:
            if self._news_skip_date != today_ny:
                logger.info(f"[SB] News day {today_ny} — trading paused for high-impact macro releases")
                self._news_skip_date = today_ny
            if self._pending_ticket is not None:
                self._cancel_pending()
            if self._open_ticket is not None:
                self._time_exit(symbol)
            return

        # 3. Manage open position
        if self._open_ticket is not None:
            logger.info(f"[SB] Managing open position | #{self._open_ticket}")
            self._sync_position(symbol)
            if self._open_ticket is not None:
                positions = mt5.positions_get(ticket=self._open_ticket) or []
                if positions:
                    pos  = positions[0]
                    side = "LONG" if pos.type == mt5.ORDER_TYPE_BUY else "SHORT"
                    logger.info(
                        f"[SB] Position status | #{pos.ticket} | {side} | "
                        f"Price={pos.price_current:.2f} | P&L=${pos.profit:+.2f}"
                    )
                self._check_breakeven(symbol)
            if self._open_ticket is not None:
                # Regular-window trade: close when window ends.
                # Off-hours trade: close at daily cutoff.
                should_exit = (
                    (not self._open_is_off_hours and not in_window) or
                    (self._open_is_off_hours and past_cutoff)
                )
                logger.info(f"[SB] Time-exit check | should_exit={should_exit}")
                if should_exit:
                    self._time_exit(symbol)
            logger.info("[SB] Cycle end | open position management complete")
            return

        # 4. Manage pending order
        if self._pending_ticket is not None:
            should_cancel = (
                (not self._pending_is_off_hours and not in_window) or
                (self._pending_is_off_hours and past_cutoff)
            )
            logger.info(
                f"[SB] Managing pending order | #{self._pending_ticket} | "
                f"off_hours={self._pending_is_off_hours} | should_cancel={should_cancel}"
            )
            if should_cancel:
                self._cancel_pending()
            logger.info("[SB] Cycle end | pending order management complete")
            return

        # 5. Feed unprocessed bars through the signal generator
        latest_idx = len(times) - 1  # most recent completed bar
        bars_to_process = sum(
            1 for ts in times
            if self._last_bar_time is None or ts > self._last_bar_time
        )
        logger.info(
            f"[SB] Signal scan start | total_bars={len(times)} | "
            f"new_bars={bars_to_process} | latest_idx={latest_idx}"
        )
        processed_count = 0
        skipped_count = 0
        signal_count = 0
        for i, ts in enumerate(times):
            if self._last_bar_time is not None and ts <= self._last_bar_time:
                skipped_count += 1
                continue
            processed_count += 1

            ts_ny    = ts.astimezone(NY_TZ)
            date_str = ts_ny.date().isoformat()

            bar_in_reg, bar_wid = self._window_at(ts_ny)
            bar_off_hrs = (
                self._cfg.off_hours_trading
                and not bar_in_reg
                and not self._is_cutoff(ts_ny)
            )
            bar_in_win = bar_in_reg or bar_off_hrs

            # Off-hours window ID: 100 + hour gives each clock-hour its own
            # fresh sweep/FVG session so the signal generator starts clean.
            if bar_in_reg:
                effective_wid = bar_wid
            elif bar_off_hrs:
                effective_wid = 100 + ts_ny.hour
            else:
                effective_wid = 0

            if bar_in_win:
                label = f"off-hrs h{ts_ny.hour}" if bar_off_hrs else f"w{effective_wid}"
                logger.info(
                    f"[SB] Scanning | {ts_ny.strftime('%H:%M')} NY | "
                    f"{label} | {'init' if not self._initialized else 'live'}"
                )

            # Use tighter scalp parameters for off-hours setups.
            original_cfg = self._generator._cfg
            if bar_off_hrs:
                self._generator._cfg = self._off_hours_cfg()
            try:
                signal = self._generator.on_bar(
                    bar_idx=i,
                    highs=highs,
                    lows=lows,
                    closes=closes,
                    opens=opens,
                    in_window=bar_in_win,
                    window_id=effective_wid,
                    date_str=date_str,
                )
            finally:
                self._generator._cfg = original_cfg

            # Act on today's signals. On the very first cycle, only trade the
            # most recent completed bar so we don't fire on stale history.
            if signal is not None:
                signal_count += 1
            if signal is not None and date_str == today_ny:
                if not self._initialized and i != latest_idx:
                    logger.info(
                        f"[SB] Signal skipped | init warmup | bar={i} latest={latest_idx}"
                    )
                    continue
                if bar_off_hrs and self._off_hours_fills >= self._cfg.off_hours_max_trades:
                    logger.info(
                        f"[SB] Off-hours cap ({self._cfg.off_hours_max_trades}) reached — skipping"
                    )
                    continue
                lots = self._compute_lots(symbol, signal)
                if lots is not None:
                    if self._cfg.use_market_order:
                        self._place_market(symbol, signal, lots, bar_off_hrs)
                    else:
                        self._place_limit(symbol, signal, lots)
                        self._open_signal          = signal
                        self._pending_is_off_hours = bar_off_hrs
                break  # one pending order per cycle
            elif signal is not None:
                logger.info(
                    f"[SB] Signal skipped | init={self._initialized} | "
                    f"date={date_str} today={today_ny}"
                )

        logger.info(
            f"[SB] Signal scan complete | processed={processed_count} | "
            f"skipped_already_seen={skipped_count} | signals_found={signal_count}"
        )

        # Advance the watermark
        if times:
            self._last_bar_time = times[-1]

        self._initialized = True
        logger.info("[SB] Cycle end | watermark advanced | init=True")

    def shutdown(self, symbol: str) -> None:
        """Cancel pending orders and close open position on shutdown."""
        if self._pending_ticket is not None:
            self._cancel_pending()
        if self._open_ticket is not None:
            self._time_exit(symbol)

    # ------------------------------------------------------------------
    # MT5 operations
    # ------------------------------------------------------------------

    def _fetch_bars(self, symbol: str, n: int) -> Optional[pd.DataFrame]:
        if not mt5.symbol_info(symbol):
            mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[["open", "high", "low", "close"]]

    def _market_is_open(self, symbol: str) -> bool:
        """Best-effort check whether the symbol is currently tradeable.

        trade_mode == FULL only means the symbol *can* be traded, not that the
        market session is open right now. We therefore also require a recent
        tick (within the last 5 minutes). When the exchange is closed the last
        tick timestamp freezes.
        """
        from datetime import datetime, timezone

        tick = mt5.symbol_info_tick(symbol)
        sym = mt5.symbol_info(symbol)
        if tick is None or sym is None:
            return False
        if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            return False
        last_tick = datetime.fromtimestamp(tick.time, tz=timezone.utc)
        age_sec = (datetime.now(tz=timezone.utc) - last_tick).total_seconds()
        return age_sec < 300  # 5 minutes

    def _sync_fill_status(self, symbol: str) -> None:
        """Detect when the pending limit order is filled and becomes a position."""
        if self._pending_ticket is None:
            return

        from src.logger import logger

        # Check if the order still exists in the pending queue
        all_orders = mt5.orders_get() or []
        if any(o.ticket == self._pending_ticket for o in all_orders):
            return  # still waiting

        # Order gone — look for a matching position
        positions = mt5.positions_get(symbol=symbol) or []
        for pos in positions:
            if pos.magic == SB_MAGIC:
                self._open_ticket        = pos.ticket
                self._open_fill_price    = pos.price_open
                self._breakeven_triggered = False
                self._trail_best_price   = None
                self._open_is_off_hours  = self._pending_is_off_hours
                if self._pending_is_off_hours:
                    self._off_hours_fills += 1
                self._pending_ticket = None
                record_ticket(pos.ticket)
                label = " [off-hours]" if self._open_is_off_hours else ""
                logger.info(
                    f"[SB] Limit filled → position #{pos.ticket} "
                    f"@ {pos.price_open:.2f}{label}"
                )
                return

        # Order disappeared without creating a position (expired / rejected)
        logger.info(f"[SB] Pending #{self._pending_ticket} removed without fill")
        self._pending_ticket = None

    def _sync_position(self, symbol: str) -> None:
        """Clear open_ticket when MT5 closes the position via SL or TP."""
        if self._open_ticket is None:
            return
        positions = mt5.positions_get(ticket=self._open_ticket) or []
        if not positions:
            from src.logger import logger
            logger.info(f"[SB] Position #{self._open_ticket} closed by MT5 (SL/TP)")
            self._open_ticket         = None
            self._open_signal         = None
            self._open_fill_price     = None
            self._breakeven_triggered = False
            self._trail_best_price    = None
            self._open_is_off_hours   = False

    def _check_breakeven(self, symbol: str) -> None:
        """Move stop to entry at breakeven_r; then trail at trail_r beyond that."""
        if self._open_signal is None or self._open_fill_price is None:
            return

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return

        from src.logger import logger

        # Off-hours positions use their own tighter breakeven/trail parameters.
        cfg_eff = self._off_hours_cfg() if self._open_is_off_hours else self._cfg

        sig      = self._open_signal
        fill     = self._open_fill_price
        risk_pts = abs(fill - sig.stop_price)
        is_long  = sig.direction == "long"
        current_px = tick.bid if is_long else tick.ask

        # Phase 1 — breakeven
        if not self._breakeven_triggered and cfg_eff.breakeven_r > 0:
            trigger_dist = risk_pts * cfg_eff.breakeven_r
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
                d        = sym_info.digits if sym_info else 2
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
                        f"[SB] Breakeven triggered | #{pos.ticket} | SL moved to {fill:.2f}"
                    )

        # Phase 2 — trailing stop (only after breakeven)
        if self._breakeven_triggered and cfg_eff.trail_r > 0:
            if is_long:
                if self._trail_best_price is None or current_px > self._trail_best_price:
                    self._trail_best_price = current_px
                new_sl = self._trail_best_price - risk_pts * cfg_eff.trail_r
            else:
                if self._trail_best_price is None or current_px < self._trail_best_price:
                    self._trail_best_price = current_px
                new_sl = self._trail_best_price + risk_pts * cfg_eff.trail_r

            positions = mt5.positions_get(ticket=self._open_ticket) or []
            if not positions:
                return
            pos      = positions[0]
            sym_info = mt5.symbol_info(symbol)
            d        = sym_info.digits if sym_info else 2
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
                        f"[SB] Trail stop updated | #{pos.ticket} | SL moved to {new_sl:.2f}"
                    )

    def _place_limit(self, symbol: str, signal: Signal, lots: float) -> None:
        from src.logger import logger

        if self._cfg.skip_news_days and is_news_day(datetime.now(NY_TZ).date()):
            logger.warning("[SB] Limit order blocked — high-impact news day")
            return

        if not self._validate_symbol(symbol):
            return

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[SB] Symbol {symbol} not found")
            return
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        order_type = (
            mt5.ORDER_TYPE_BUY_LIMIT
            if signal.direction == "long"
            else mt5.ORDER_TYPE_SELL_LIMIT
        )
        d = sym_info.digits

        request = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       symbol,
            "volume":       lots,
            "type":         order_type,
            "price":        round(signal.entry_price, d),
            "sl":           round(signal.stop_price,  d),
            "tp":           round(signal.target_price, d),
            "deviation":    20,
            "magic":        SB_MAGIC,
            "comment":      "SilverBullet",
            "type_time":    mt5.ORDER_TIME_DAY,    # auto-expires if still pending at day end
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }

        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            self._pending_ticket = result.order
            logger.info(
                f"[SB] LIMIT {signal.direction.upper()} | {symbol} | "
                f"Lots={lots:.2f} | Entry={signal.entry_price:.2f} "
                f"SL={signal.stop_price:.2f} TP={signal.target_price:.2f} "
                f"| #{result.order}"
            )
        else:
            logger.error(
                f"[SB] Limit order failed | code={result.retcode} | {result.comment}"
            )

    def _place_market(self, symbol: str, signal: Signal, lots: float, is_off_hrs: bool) -> None:
        from src.logger import logger

        if self._cfg.skip_news_days and is_news_day(datetime.now(NY_TZ).date()):
            logger.warning("[SB] Market order blocked — high-impact news day")
            return

        if not self._validate_symbol(symbol):
            return

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[SB] Symbol {symbol} not found")
            return
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"[SB] No tick data for {symbol}")
            return

        is_long    = signal.direction == "long"
        order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL

        # Price used for the market-order request.
        price = tick.ask if is_long else tick.bid
        # MT5 validates BUY stops against BID and SELL stops against ASK.
        stop_price = tick.bid if is_long else tick.ask
        d = sym_info.digits

        # Skip stale signals. If price has already moved past the signal entry
        # by more than the original risk, the setup is gone and adjusting stops
        # would create a bad R:R trade.
        risk_pts = abs(signal.entry_price - signal.stop_price)
        entry_slip = abs(price - signal.entry_price)
        if entry_slip > risk_pts * 0.5:
            logger.info(
                f"[SB] Signal stale | Price={price:.2f} Entry={signal.entry_price:.2f} "
                f"slip={entry_slip:.1f}pts (risk={risk_pts:.1f}pts) — skipping market entry"
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

        logger.info(
            f"[SB] Broker min_dist={min_dist:.1f} | "
            f"SL adjusted: {signal.stop_price:.2f}→{sl:.2f} | "
            f"TP adjusted: {signal.target_price:.2f}→{tp:.2f}"
        )

        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       lots,
            "type":         order_type,
            "price":        round(price, d),
            "sl":           sl,
            "tp":           tp,
            "deviation":    20,
            "magic":        SB_MAGIC,
            "comment":      "SilverBullet_MKT",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            positions = mt5.positions_get(ticket=result.order) or []
            fill_price = positions[0].price_open if positions else price
            self._open_ticket         = result.order
            self._open_fill_price     = fill_price
            self._open_signal         = signal
            self._open_is_off_hours   = is_off_hrs
            self._breakeven_triggered = False
            self._trail_best_price    = None
            if is_off_hrs:
                self._off_hours_fills += 1
            record_ticket(result.order)
            logger.info(
                f"[SB] MARKET {signal.direction.upper()} | {symbol} | "
                f"Lots={lots:.2f} | Fill={fill_price:.2f} "
                f"SL={sl:.2f} TP={tp:.2f} | #{result.order}"
            )
        else:
            logger.error(
                f"[SB] Market order failed | code={result.retcode} | {result.comment}"
            )

    def _cancel_pending(self) -> None:
        if self._pending_ticket is None:
            return
        from src.logger import logger

        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_REMOVE,
            "order":  self._pending_ticket,
        })
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[SB] Pending #{self._pending_ticket} cancelled (window ended)")
        else:
            logger.warning(
                f"[SB] Cancel failed | code={result.retcode} | {result.comment}"
            )
        self._pending_ticket = None

    def _time_exit(self, symbol: str) -> None:
        if self._open_ticket is None:
            return
        from src.logger import logger

        positions = mt5.positions_get(ticket=self._open_ticket) or []
        if not positions:
            self._open_ticket = None
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
            "magic":        SB_MAGIC,
            "comment":      "SB_time_exit",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[SB] Time exit | #{pos.ticket} | PnL ${pos.profit:.2f}")
            self._open_ticket         = None
            self._open_signal         = None
            self._open_fill_price     = None
            self._breakeven_triggered = False
            self._trail_best_price    = None
            self._open_is_off_hours   = False
        else:
            logger.error(
                f"[SB] Time exit failed | code={result.retcode} | {result.comment}"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_symbol(self, symbol: str) -> bool:
        """Guard against trading the wrong instrument.

        If the adapter was constructed with an explicit symbol, every cycle
        must use that symbol.  This prevents a misconfigured caller or another
        bot instance from opening positions on the wrong instrument.
        """
        from src.logger import logger

        if not symbol:
            logger.error("[SB] No symbol provided to adapter cycle — skipping")
            return False

        if self._symbol is not None and symbol != self._symbol:
            logger.error(
                f"[SB] Symbol mismatch | expected={self._symbol} received={symbol}. "
                f"Skipping cycle to avoid wrong-instrument execution."
            )
            return False

        return True

    def _window_at(self, ts_ny: datetime) -> tuple[bool, Optional[int]]:
        t = ts_ny.time()
        for wid, (start_s, end_s) in enumerate(self._cfg.windows):
            sh, sm = map(int, start_s.split(":"))
            eh, em = map(int, end_s.split(":"))
            if dtime(sh, sm) <= t < dtime(eh, em):
                return True, wid
        return False, None

    def _window_status_desc(self, ts_ny: datetime) -> str:
        """Human-readable session status: time left in window, or time to the next one."""
        t = ts_ny.time()
        for start_s, end_s in self._cfg.windows:
            sh, sm = map(int, start_s.split(":"))
            eh, em = map(int, end_s.split(":"))
            if dtime(sh, sm) <= t < dtime(eh, em):
                end_dt = ts_ny.replace(hour=eh, minute=em, second=0, microsecond=0)
                mins_left = max(0, int((end_dt - ts_ny).total_seconds() // 60))
                return f"in window, {mins_left}m left"

        upcoming = []
        for start_s, end_s in self._cfg.windows:
            sh, sm = map(int, start_s.split(":"))
            start_dt = ts_ny.replace(hour=sh, minute=sm, second=0, microsecond=0)
            if start_dt <= ts_ny:
                start_dt += timedelta(days=1)
            upcoming.append((start_dt, start_s, end_s))
        if not upcoming:
            return "no session windows configured"
        upcoming.sort(key=lambda u: u[0])
        next_dt, next_start, next_end = upcoming[0]
        delta = next_dt - ts_ny
        hrs, rem = divmod(int(delta.total_seconds()), 3600)
        mins = rem // 60
        return f"next window {next_start}-{next_end} ET in {hrs}h{mins:02d}m"

    def _off_hours_cfg(self) -> SilverBulletConfig:
        """Return a config copy with tighter scalp parameters for off-hours."""
        c = self._cfg
        return _dc_replace(
            c,
            fvg_min_points     = c.off_hours_fvg_min_points,
            min_risk_points    = c.off_hours_min_risk_points,
            target_mode        = c.off_hours_target_mode,
            rr                 = c.off_hours_rr,
            breakeven_r        = c.off_hours_breakeven_r,
            trail_r            = c.off_hours_trail_r,
            early_exit_r       = c.off_hours_early_exit_r,
            deep_profit_r      = c.off_hours_deep_profit_r,
            deep_trail_r       = c.off_hours_deep_trail_r,
        )

    def _is_cutoff(self, ts_ny: datetime) -> bool:
        """True once we've passed the off-hours daily close time."""
        h, m = map(int, self._cfg.off_hours_close_time.split(":"))
        return ts_ny.time() >= dtime(h, m)

    def _compute_lots(self, symbol: str, signal: Signal) -> Optional[float]:
        from src.logger import logger

        sym_info = mt5.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[SB] No symbol info for {symbol}")
            return None

        account = mt5.account_info()
        if account is None:
            return None

        # Use the more conservative of balance or equity so an open
        # drawdown does not inflate position size on a small account.
        usable_capital = min(account.balance, account.equity)
        if usable_capital <= 0:
            logger.error("[SB] Account balance/equity is zero or negative — cannot size position")
            return None

        # Hard balance floor: refuse to trade if the account is below the
        # configured minimum.  For a $100 account the default ($15) leaves
        # headroom for spread/commission and avoids margin errors from
        # minimum-lot sizing.
        min_balance = getattr(root_config, "SB_MIN_BALANCE", 15.0)
        if usable_capital < min_balance:
            logger.warning(
                f"[SB] Usable capital ${usable_capital:.2f} is below the "
                f"configured minimum ${min_balance:.2f} — skipping trade"
            )
            return None

        # Clamp SB_RISK_PCT to a sane range.  On accounts under $200 also
        # enforce a 2% ceiling so a misconfigured env var cannot blow up
        # a micro account in one trade.
        risk_pct = max(0.01, min(float(root_config.SB_RISK_PCT), 100.0))
        if usable_capital < 200.0:
            risk_pct = min(risk_pct, 2.0)

        risk_usd = usable_capital * (risk_pct / 100.0)

        # Capital-preservation cap: while the account is below the small-account
        # threshold, never risk more than SB_MAX_RISK_USD on a single trade.
        small_acct_threshold = getattr(root_config, "SB_SMALL_ACCT_THRESHOLD", 150.0)
        max_risk_usd = getattr(root_config, "SB_MAX_RISK_USD", 1.0)
        if usable_capital < small_acct_threshold:
            capped_risk_usd = min(risk_usd, max_risk_usd)
            if capped_risk_usd < risk_usd:
                logger.info(
                    f"[SB] Small-account cap | Risk reduced from ${risk_usd:.2f} "
                    f"to ${capped_risk_usd:.2f} (balance below ${small_acct_threshold:.0f})"
                )
            risk_usd = capped_risk_usd

        risk_pts = abs(signal.entry_price - signal.stop_price)
        tick_val = sym_info.trade_tick_value
        tick_size = sym_info.trade_tick_size

        if risk_pts <= 0 or tick_val <= 0 or tick_size <= 0:
            logger.warning(
                f"[SB] Invalid sizing inputs: risk_pts={risk_pts}, "
                f"tick_val={tick_val}, tick_size={tick_size} — using volume_min"
            )
            return sym_info.volume_min

        value_per_pt = tick_val / tick_size
        raw = risk_usd / (risk_pts * value_per_pt)
        step = sym_info.volume_step
        lots = round(raw / step) * step
        lots = max(sym_info.volume_min, min(lots, sym_info.volume_max, 1.0))

        # If broker rounding / minimum volume forces us to risk more than
        # 5% of capital, skip the trade rather than overshoot.
        actual_risk_usd = lots * risk_pts * value_per_pt
        if actual_risk_usd > usable_capital * 0.05:
            logger.warning(
                f"[SB] Sizing overshoot: {lots} lots would risk "
                f"${actual_risk_usd:.2f} ({actual_risk_usd / usable_capital * 100:.1f}% "
                f"of capital). Skipping trade."
            )
            return None

        logger.info(
            f"[SB] Sizing | Capital=${usable_capital:.2f} RiskPct={risk_pct:.2f}% "
            f"Risk=${risk_usd:.2f} SL={risk_pts:.1f}pts RawLots={raw:.3f} "
            f"FinalLots={lots:.2f} TickVal={tick_val:.5f}/TickSize={tick_size}"
        )
        return round(lots, 2)

    def _check_daily_limits(self, symbol: str) -> bool:
        """Return True if new trades are allowed today.

        Enforces SB_DAILY_LOSS_LIMIT_USD and SB_MAX_TRADES_PER_DAY by querying
        MT5 history for today's closed Silver Bullet deals.  The limits reset
        at the start of each NY trading day.
        """
        from datetime import datetime, timezone
        from src.logger import logger

        today_ny = datetime.now(NY_TZ).date().isoformat()

        # Reset on new day
        if today_ny != self._daily_limit_date:
            self._daily_limit_date = today_ny
            self._daily_loss_usd = 0.0
            self._daily_trades = 0
            self._daily_limit_halted = False
            logger.info(f"[SB] Daily limits reset for {today_ny}")

        if self._daily_limit_halted:
            return False

        # Recompute from MT5 history so a restart does not bypass the limit.
        ny_midnight = datetime.now(NY_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        from_date = ny_midnight.astimezone(timezone.utc)
        to_date = datetime.now(timezone.utc)

        try:
            deals = mt5.history_deals_get(from_date, to_date) or []
        except Exception as exc:
            logger.warning(f"[SB] Failed to fetch history deals: {exc}")
            deals = []

        daily_pnl = 0.0
        daily_entries = 0
        for deal in deals:
            if deal.magic != SB_MAGIC:
                continue
            if deal.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                daily_pnl += deal.profit + deal.commission + deal.swap
                # Count entries (the opening half of a position)
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    daily_entries += 1

        self._daily_loss_usd = daily_pnl
        self._daily_trades = daily_entries

        loss_limit = getattr(root_config, "SB_DAILY_LOSS_LIMIT_USD", 3.0)
        max_trades = getattr(root_config, "SB_MAX_TRADES_PER_DAY", 2)

        if daily_pnl <= -abs(loss_limit):
            logger.warning(
                f"[SB] Daily loss limit reached | PnL ${daily_pnl:.2f} <= -${loss_limit:.2f}. "
                f"No new trades today."
            )
            self._daily_limit_halted = True
            return False

        if daily_entries >= max_trades:
            logger.info(
                f"[SB] Daily trade cap reached | {daily_entries}/{max_trades} trades. "
                f"No new trades today."
            )
            self._daily_limit_halted = True
            return False

        return True

    def _check_drawdown_floor(self, symbol: str) -> bool:
        """Return True if trading is allowed; halt and flatten if floor is breached.

        The floor is computed from the balance seen at bot start.  Once the
        more conservative of balance/equity drops below that floor, all
        trading stops, pending orders are cancelled and open positions are
        closed.  The bot must be restarted to resume.
        """
        from src.logger import logger

        if self._drawdown_halted:
            return False

        account = mt5.account_info()
        if account is None:
            return False

        usable_capital = min(account.balance, account.equity)
        if usable_capital <= 0:
            return False

        # Record starting balance on first call.
        if self._drawdown_floor is None:
            drawdown_pct = max(0.0, min(float(root_config.SB_MAX_DRAWDOWN_PCT), 100.0))
            self._drawdown_floor = usable_capital * (1.0 - drawdown_pct / 100.0)
            logger.info(
                f"[SB] Drawdown floor set | Start=${usable_capital:.2f} "
                f"Floor=${self._drawdown_floor:.2f} (max {drawdown_pct:.1f}% loss)"
            )

        if usable_capital <= self._drawdown_floor:
            logger.warning(
                f"[SB] CIRCUIT BREAKER | Capital ${usable_capital:.2f} hit floor "
                f"${self._drawdown_floor:.2f}. Halting all trading and flattening."
            )
            self._drawdown_halted = True
            self._cancel_pending()
            if self._open_ticket is not None:
                self._time_exit(symbol)
            return False

        return True
