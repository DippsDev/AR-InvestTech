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
- Multiple pending orders and open positions can be live at once, each tracked by
  its own MT5 ticket in `_pending`/`_open`. There is no one-trade-at-a-time gate —
  the only throttle on how many trades happen in a day is SB_MAX_TRADES_PER_DAY
  (enforced in _check_daily_limits). The signal generator's own one-trade-per-window
  rule still prevents firing twice off the same sweep/FVG session.
- Magic number 202406122 is reserved for the Silver Bullet strategy.
"""
from __future__ import annotations

from dataclasses import dataclass, replace as _dc_replace
from datetime import datetime, time as dtime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import pandas as pd

import config as root_config

from src import mt5_cache
from src.split_target import split_lots
from src.ticket_store import load_tickets, record_ticket

from .config import SilverBulletConfig
from .news_calendar import is_news_day
from .strategy import Signal, SignalGenerator

NY_TZ = ZoneInfo("America/New_York")
SB_MAGIC = 202406122


@dataclass
class _PendingOrder:
    """A not-yet-filled limit order this adapter placed."""
    signal: Signal
    is_off_hours: bool


@dataclass
class _OpenPosition:
    """A filled position this adapter is managing (breakeven/trail/time-exit)."""
    signal: Signal
    fill_price: float
    is_off_hours: bool
    breakeven_triggered: bool = False
    trail_best_price: Optional[float] = None


class SilverBulletLiveAdapter:
    """Stateful, bar-by-bar adapter.  Instantiate once; call .cycle() every 30 s."""

    # Silver Bullet reads M5 bars — used by _idle_between_bars to tell whether
    # a new bar has closed without paying for a fetch to find out.
    _BAR_PERIOD_SEC = 300

    def __init__(self, cfg: SilverBulletConfig, symbol: Optional[str] = None,
                 risk_pct_override: Optional[float] = None):
        self._cfg = cfg
        self._generator = SignalGenerator(cfg)
        # Symbol we are allowed to trade.  All MT5 operations are guarded against
        # this to prevent cross-instrument execution.
        self._symbol: Optional[str] = symbol
        # When multiple instances of this strategy run concurrently on
        # different symbols, each is given a fraction of SB_RISK_PCT
        # (see bot.py) so total account risk stays comparable to a single
        # instance. None means "use SB_RISK_PCT directly" (single-instance,
        # default behavior).
        self._risk_pct_override: Optional[float] = risk_pct_override
        self._last_bar_time: Optional[pd.Timestamp] = None  # last processed bar timestamp
        # Bar-period boundary this adapter last ran a full scan at, so an idle
        # adapter fetches bars once per M5 bar instead of once per loop tick.
        self._last_bar_slot: Optional[int] = None
        # Pending orders and open positions this adapter placed, keyed by MT5
        # ticket — a dict rather than a single slot so several can be live at
        # once (see module docstring).
        self._pending: dict[int, _PendingOrder] = {}
        self._open: dict[int, _OpenPosition] = {}
        self._initialized: bool = False                      # False on very first cycle
        # Off-hours tracking
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
        # Broker/trade-server clock offset from true UTC, remeasured each
        # cycle — see src/broker_time.py.
        self._broker_utc_offset: timedelta = timedelta(0)
        # Adaptive daily-trade floor: bot.py sets this each loop tick to the
        # combined SB+TL trade count for today (see _boost_active below).
        self.combined_daily_trades: int = 0
        self._boost_notified: bool = False
        # Decimal places for prices in log output, refreshed from symbol_info
        # once per cycle. 2 until the first cycle resolves the real value.
        self._digits: int = 2

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _px(self, value: float) -> str:
        """Format a price at the symbol's precision.

        A fixed 2dp collapses every price on a 5-digit FX pair to the same
        number — entry, stop and target all log as "1.15" — so a fill cannot
        be checked against the signal that produced it.
        """
        return f"{value:.{self._digits}f}"

    def _sync_digits(self, symbol: str) -> None:
        """Pick up the symbol's price precision for this cycle's logging."""
        sym_info = mt5_cache.symbol_info(symbol)
        if sym_info is not None:
            self._digits = sym_info.digits
            self._generator.set_digits(sym_info.digits)

    def cycle(self, symbol: str) -> None:
        """Called from the main bot loop.  Manages the full lifecycle of one SB setup."""
        from src.logger import logger

        logger.debug(
            f"[SB] Cycle start | symbol={symbol} | initialized={self._initialized} | "
            f"pending={list(self._pending)} | open={list(self._open)}"
        )

        if not self._validate_symbol(symbol):
            logger.debug("[SB] Cycle aborted | symbol validation failed")
            return

        self._sync_digits(symbol)

        # MT5 timestamps (bars, ticks, deals) are stamped in the broker's own
        # server clock, not true UTC — measure the current offset once per
        # cycle so every NY-session/news-day/daily-count calc below can
        # correct for it. See src/broker_time.py.
        self._broker_utc_offset = mt5_cache.broker_utc_offset(symbol)

        # Circuit breaker: halt if drawdown exceeds configured limit.
        if self._drawdown_halted:
            logger.debug("[SB] Cycle skipped | drawdown circuit breaker active")
            return
        if not self._check_drawdown_floor(symbol):
            logger.debug("[SB] Cycle skipped | drawdown floor breached")
            return

        # Daily entry cap: this only gates NEW entries later in the cycle
        # (step 5) — pending/open trades already on the books are still
        # synced and managed below regardless, so reaching the cap never
        # leaves an existing trade without breakeven/trailing/time-exit for
        # the rest of the day.
        can_enter_new = self._check_daily_limits(symbol)

        # With nothing on the books and no newly-closed bar, everything below
        # can only re-derive facts this adapter already holds — see
        # _idle_between_bars.
        if self._idle_between_bars():
            logger.debug("[SB] Cycle skipped | idle, no new M5 bar since last scan")
            return

        bars = self._fetch_bars(symbol, n=150)
        if bars is None or len(bars) < 10:
            if not self._market_is_open(symbol):
                logger.debug(f"[SB] Market closed for {symbol} — waiting for reopen")
            else:
                logger.warning(f"[SB] Bar fetch failed for {symbol}")
            return

        # Bars come back timestamped in the broker's server clock (labeled
        # "UTC" but not actually true UTC on some brokers) — correct to true
        # UTC before any NY-session-window math is done on them.
        bars.index = bars.index - self._broker_utc_offset

        # Drop the currently-forming (incomplete) bar
        completed = bars.iloc[:-1]
        if completed.empty:
            logger.debug("[SB] Cycle skipped | no completed bars available")
            return

        # Bars are in hand, so this bar period counts as scanned regardless of
        # what the rest of the cycle decides. Marking it here rather than in
        # the gate means a failed or empty fetch above retries on the next
        # tick instead of waiting out a whole bar.
        self._mark_bar_scanned()

        logger.debug(
            f"[SB] Bars fetched | total={len(bars)} completed={len(completed)} | "
            f"first={completed.index[0]} UTC | last={completed.index[-1]} UTC"
        )

        times  = completed.index.tolist()          # list of tz-aware UTC pd.Timestamps
        highs  = completed["high"].to_numpy(dtype=float)
        lows   = completed["low"].to_numpy(dtype=float)
        closes = completed["close"].to_numpy(dtype=float)
        opens  = completed["open"].to_numpy(dtype=float)

        # 1. Check if any pending orders were filled by MT5
        logger.debug(
            f"[SB] Syncing fill status | pending={list(self._pending)} | open={list(self._open)}"
        )
        self._sync_fill_status(symbol)
        logger.debug(
            f"[SB] Fill status synced | pending={list(self._pending)} | open={list(self._open)}"
        )

        # 2. Determine session context
        last_ny = times[-1].astimezone(NY_TZ)
        in_window, _ = self._window_at(last_ny)
        past_cutoff  = self._is_cutoff(last_ny)
        in_off_hours = self._cfg.off_hours_trading and not in_window and not past_cutoff
        window_desc = self._window_status_desc(last_ny)
        logger.debug(
            f"[SB] Session context | last_bar={last_ny.strftime('%H:%M')} NY | price={self._px(closes[-1])} | "
            f"in_window={in_window} | off_hours={in_off_hours} | past_cutoff={past_cutoff} | "
            f"{window_desc} | Today: {self._daily_trades} trades, PnL ${self._daily_loss_usd:+.2f}"
        )

        # Reset daily off-hours fill counter at day change
        today_ny = datetime.now(NY_TZ).date().isoformat()
        if today_ny != self._off_hours_date:
            self._off_hours_date  = today_ny
            self._off_hours_fills = 0

        # News-day circuit breaker: no new entries on high-impact macro days,
        # and flatten everything already on the books.
        news_skip = self._cfg.skip_news_days and is_news_day(today_ny)
        if news_skip:
            if self._news_skip_date != today_ny:
                logger.info(f"[SB] News day {today_ny} — trading paused for high-impact macro releases")
                self._news_skip_date = today_ny
            for ticket in list(self._pending):
                self._cancel_pending(ticket)
            for ticket in list(self._open):
                self._time_exit(symbol, ticket)
            return

        # 3. Manage every open position — breakeven/trail, then time-exit if
        #    its window has ended. Runs even if the daily cap has been hit.
        self._sync_position(symbol)
        for ticket in list(self._open):
            pos = self._open.get(ticket)
            if pos is None:
                continue  # closed by MT5 during this loop (e.g. via _check_breakeven)
            logger.debug(f"[SB] Managing open position | #{ticket}")
            positions = mt5_cache.positions_get(ticket=ticket)
            if positions:
                live = positions[0]
                side = "LONG" if live.type == mt5.ORDER_TYPE_BUY else "SHORT"
                logger.debug(
                    f"[SB] Position status | #{live.ticket} | {side} | "
                    f"Price={live.price_current:.2f} | P&L=${live.profit:+.2f}"
                )
            self._check_breakeven(symbol, ticket)
            if ticket not in self._open:
                continue
            # Regular-window trade: close when window ends.
            # Off-hours trade: close at daily cutoff.
            # LOSS-ONLY rule (2026-08-15, owner request): the time exit exists
            # to cut trades that did not work within their window — a position
            # in profit is already protected by breakeven/trailing and is left
            # to run to its TP or trail stop instead of being flattened on a
            # clock boundary. News-day flatten and shutdown() close everything
            # regardless of P&L — only this window-end path is loss-only.
            pos = self._open[ticket]
            should_exit = (
                (not pos.is_off_hours and not in_window) or
                (pos.is_off_hours and past_cutoff)
            )
            if should_exit:
                live = mt5_cache.positions_get(ticket=ticket)
                if live and live[0].profit >= 0:
                    logger.debug(
                        f"[SB] Time-exit skipped | #{ticket} | P&L=${live[0].profit:+.2f} "
                        f"— in profit at window end, left running (BE/trail still active)"
                    )
                    continue
                self._time_exit(symbol, ticket)

        # 4. Manage every pending order — cancel any whose window has ended.
        for ticket in list(self._pending):
            pend = self._pending.get(ticket)
            if pend is None:
                continue
            should_cancel = (
                (not pend.is_off_hours and not in_window) or
                (pend.is_off_hours and past_cutoff)
            )
            logger.debug(
                f"[SB] Managing pending order | #{ticket} | "
                f"off_hours={pend.is_off_hours} | should_cancel={should_cancel}"
            )
            if should_cancel:
                self._cancel_pending(ticket)

        if not can_enter_new:
            logger.debug("[SB] Cycle end | new entries blocked by daily limit")
            return

        # 5. Feed unprocessed bars through the signal generator
        latest_idx = len(times) - 1  # most recent completed bar
        bars_to_process = sum(
            1 for ts in times
            if self._last_bar_time is None or ts > self._last_bar_time
        )
        logger.debug(
            f"[SB] Signal scan start | total_bars={len(times)} | "
            f"new_bars={bars_to_process} | latest_idx={latest_idx}"
        )
        processed_count = 0
        skipped_count = 0
        signal_count = 0
        boost_active = self._boost_active()
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
                logger.debug(
                    f"[SB] Scanning | {ts_ny.strftime('%H:%M')} NY | "
                    f"{label} | {'init' if not self._initialized else 'live'}"
                )

            # Use tighter scalp parameters for off-hours setups, then relax
            # further on top of that if the adaptive daily-trade floor has
            # kicked in.
            original_cfg = self._generator._cfg
            effective_cfg = self._off_hours_cfg() if bar_off_hrs else self._cfg
            if boost_active:
                effective_cfg = self._boosted_cfg(effective_cfg)
            self._generator._cfg = effective_cfg
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
                    logger.debug(
                        f"[SB] Signal skipped | init warmup | bar={i} latest={latest_idx}"
                    )
                    continue
                if bar_off_hrs and self._off_hours_fills >= self._cfg.off_hours_max_trades:
                    logger.debug(
                        f"[SB] Off-hours cap ({self._cfg.off_hours_max_trades}) reached — skipping"
                    )
                    continue
                if self._stop_inside_spread(symbol, signal):
                    continue
                from news_analyst import reject_entry
                blocked = reject_entry(symbol, signal.direction, today_ny)
                if blocked:
                    logger.info(f"[Analyst] Entry blocked | {blocked}")
                    continue
                lots = self._compute_lots(symbol, signal)
                if lots is not None:
                    logger.info(
                        f"[SB] About to place order | {signal.direction.upper()} | "
                        f"entry={self._px(signal.entry_price)} stop={self._px(signal.stop_price)} "
                        f"target={self._px(signal.target_price)} | lots={lots:.2f}"
                    )
                    if self._cfg.use_market_order:
                        self._place_market(symbol, signal, lots, bar_off_hrs)
                    else:
                        self._place_limit(symbol, signal, lots, bar_off_hrs)
                break  # one new order per cycle
            elif signal is not None:
                logger.debug(
                    f"[SB] Signal skipped | init={self._initialized} | "
                    f"date={date_str} today={today_ny}"
                )

        logger.debug(
            f"[SB] Signal scan complete | processed={processed_count} | "
            f"skipped_already_seen={skipped_count} | signals_found={signal_count}"
        )
        # Routine heartbeat for the dashboard's Scanner persona: fires once
        # per newly-closed bar (~every 5 min), not every cycle tick, so the
        # feed reads as periodic status rather than spam.
        if processed_count > 0 and signal_count == 0:
            logger.info(
                f"[SB] No setup on {processed_count} new bar(s) | {window_desc} | "
                f"price={self._px(closes[-1])}"
            )

        # Advance the watermark
        if times:
            self._last_bar_time = times[-1]

        self._initialized = True
        logger.debug("[SB] Cycle end | watermark advanced | init=True")

    def shutdown(self, symbol: str) -> None:
        """Cancel all pending orders and close all open positions on shutdown."""
        for ticket in list(self._pending):
            self._cancel_pending(ticket)
        for ticket in list(self._open):
            self._time_exit(symbol, ticket)

    # ------------------------------------------------------------------
    # MT5 operations
    # ------------------------------------------------------------------

    def _fetch_bars(self, symbol: str, n: int) -> Optional[pd.DataFrame]:
        if not mt5_cache.symbol_info(symbol):
            mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[["open", "high", "low", "close"]]

    def _idle_between_bars(self) -> bool:
        """True when this cycle provably has nothing to do and can be skipped.

        The bot loop ticks every 5 seconds but Silver Bullet reads M5 bars, so
        59 of every 60 cycles re-fetch 150 bars the signal generator has
        already consumed — `_last_bar_time` makes it skip every one of them.

        Skipping is only safe when *nothing else* in the cycle can act:

        * no open positions — otherwise breakeven/trailing/time-exit must keep
          running at full 5-second cadence, which is the whole point of a loop
          faster than the bar period;
        * no pending orders — otherwise fill detection and window-end
          cancellation would be delayed by up to a bar;
        * no newly-closed bar since the last scan — otherwise there is genuinely
          new price action to feed the generator.

        Under those conditions the remainder of the cycle reads bars, recomputes
        session context, iterates two empty dicts and re-scans bars it has
        already seen, so skipping changes no decision this adapter would make.

        Bar arrival is derived from the clock rather than from a fetch (which is
        the cost being avoided): the in-progress bar opens at the current
        `bar_period` boundary, so a new bar has closed exactly when that
        boundary moves. Tracking the boundary we last scanned at — rather than
        comparing against `_last_bar_time` — also keeps this correct when the
        market is closed and no new bars arrive at all, which would otherwise
        leave the watermark stuck and refetch on every tick.

        This is a pure predicate: the boundary is only marked scanned once a
        fetch has actually succeeded (see `_mark_bar_scanned`), so a failed or
        empty fetch retries on the next tick rather than waiting out a bar.
        """
        if self._open or self._pending:
            return False
        return self._current_bar_slot() == self._last_bar_slot

    def _current_bar_slot(self) -> int:
        """Index of the bar period in progress."""
        from datetime import datetime, timezone

        return int(datetime.now(timezone.utc).timestamp()) // self._BAR_PERIOD_SEC

    def _mark_bar_scanned(self) -> None:
        """Record that this bar period's data has been fetched and scanned."""
        self._last_bar_slot = self._current_bar_slot()

    def _market_is_open(self, symbol: str) -> bool:
        """Best-effort check whether the symbol is currently tradeable.

        trade_mode == FULL only means the symbol *can* be traded, not that the
        market session is open right now. We therefore also require a recent
        tick (within the last 5 minutes). When the exchange is closed the last
        tick timestamp freezes.
        """
        from datetime import datetime, timezone

        tick = mt5_cache.symbol_info_tick(symbol)
        sym = mt5_cache.symbol_info(symbol)
        if tick is None or sym is None:
            return False
        if sym.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            return False
        # tick.time is the broker's server clock, not true UTC — correct it
        # before measuring staleness, or a fast/slow broker clock makes this
        # check silently wrong (e.g. always "fresh" for a clock running ahead).
        last_tick = datetime.fromtimestamp(tick.time, tz=timezone.utc) - self._broker_utc_offset
        age_sec = (datetime.now(tz=timezone.utc) - last_tick).total_seconds()
        return age_sec < 300  # 5 minutes

    def _sync_fill_status(self, symbol: str) -> None:
        """Detect when a pending limit order is filled and becomes a position.

        MT5 assigns a filled pending order's resulting position the SAME
        ticket number as the order itself, so each pending ticket can be
        matched to its position directly — no need to guess by scanning all
        positions for a matching magic number, which would be ambiguous the
        moment more than one pending order is live at once.
        """
        if not self._pending:
            return

        from src.logger import logger

        all_orders = mt5.orders_get() or []
        still_pending = {o.ticket for o in all_orders}

        for ticket in list(self._pending):
            if ticket in still_pending:
                continue  # still waiting

            pend = self._pending.pop(ticket)
            positions = mt5_cache.positions_get(ticket=ticket)
            if positions:
                pos = positions[0]
                self._open[pos.ticket] = _OpenPosition(
                    signal=pend.signal,
                    fill_price=pos.price_open,
                    is_off_hours=pend.is_off_hours,
                )
                if pend.is_off_hours:
                    self._off_hours_fills += 1
                record_ticket(pos.ticket, strategy="SB")
                label = " [off-hours]" if pend.is_off_hours else ""
                logger.info(
                    f"[SB] Limit filled → position #{pos.ticket} "
                    f"@ {self._px(pos.price_open)}{label}"
                )
            else:
                # Order disappeared without creating a position (expired / rejected)
                logger.info(f"[SB] Pending #{ticket} removed without fill")

    def _sync_position(self, symbol: str) -> None:
        """Drop any open position MT5 has already closed via SL or TP."""
        if not self._open:
            return
        from src.logger import logger
        for ticket in list(self._open):
            positions = mt5_cache.positions_get(ticket=ticket)
            if not positions:
                logger.info(f"[SB] Position #{ticket} closed by MT5 (SL/TP)")
                del self._open[ticket]

    def _check_breakeven(self, symbol: str, ticket: int) -> None:
        """Move stop to entry at breakeven_r; then trail at trail_r beyond that."""
        pos = self._open.get(ticket)
        if pos is None:
            return

        tick = mt5_cache.symbol_info_tick(symbol)
        if tick is None:
            return

        from src.logger import logger

        # Off-hours positions use their own tighter breakeven/trail parameters.
        cfg_eff = self._off_hours_cfg() if pos.is_off_hours else self._cfg

        sig      = pos.signal
        fill     = pos.fill_price
        risk_pts = abs(fill - sig.stop_price)
        is_long  = sig.direction == "long"
        current_px = tick.bid if is_long else tick.ask

        # Phase 1 — breakeven
        if not pos.breakeven_triggered and cfg_eff.breakeven_r > 0:
            trigger_dist = risk_pts * cfg_eff.breakeven_r
            triggered = (
                current_px >= fill + trigger_dist if is_long
                else current_px <= fill - trigger_dist
            )
            if triggered:
                positions = mt5_cache.positions_get(ticket=ticket)
                if not positions:
                    return
                live     = positions[0]
                sym_info = mt5_cache.symbol_info(symbol)
                d        = sym_info.digits if sym_info else 2
                result   = mt5.order_send({
                    "action":   mt5.TRADE_ACTION_SLTP,
                    "symbol":   symbol,
                    "position": live.ticket,
                    "sl":       round(fill, d),
                    "tp":       round(live.tp, d),
                })
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    # The trailing phase below re-reads this position to compare
                    # against its current SL — drop the snapshot so it sees the
                    # stop we just moved, not the pre-breakeven one.
                    mt5_cache.invalidate_positions()
                    pos.breakeven_triggered = True
                    logger.debug(
                        f"[SB] Breakeven triggered | #{live.ticket} | SL moved to {self._px(fill)}"
                    )

        # Phase 2 — trailing stop (only after breakeven)
        if pos.breakeven_triggered and cfg_eff.trail_r > 0:
            if is_long:
                if pos.trail_best_price is None or current_px > pos.trail_best_price:
                    pos.trail_best_price = current_px
                new_sl = pos.trail_best_price - risk_pts * cfg_eff.trail_r
            else:
                if pos.trail_best_price is None or current_px < pos.trail_best_price:
                    pos.trail_best_price = current_px
                new_sl = pos.trail_best_price + risk_pts * cfg_eff.trail_r

            positions = mt5_cache.positions_get(ticket=ticket)
            if not positions:
                return
            live     = positions[0]
            sym_info = mt5_cache.symbol_info(symbol)
            d        = sym_info.digits if sym_info else 2
            current_sl = live.sl

            sl_improves = (new_sl > current_sl) if is_long else (new_sl < current_sl)
            if sl_improves:
                result = mt5.order_send({
                    "action":   mt5.TRADE_ACTION_SLTP,
                    "symbol":   symbol,
                    "position": live.ticket,
                    "sl":       round(new_sl, d),
                    "tp":       round(live.tp, d),
                })
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    mt5_cache.invalidate_positions()
                    logger.debug(
                        f"[SB] Trail stop updated | #{live.ticket} | SL moved to {self._px(new_sl)}"
                    )

    def _place_limit(self, symbol: str, signal: Signal, lots: float, is_off_hours: bool) -> None:
        from src.logger import logger

        if self._cfg.skip_news_days and is_news_day(datetime.now(NY_TZ).date()):
            logger.warning("[SB] Limit order blocked — high-impact news day")
            return

        from news_analyst import reject_entry
        blocked = reject_entry(symbol, signal.direction)
        if blocked:
            logger.info(f"[Analyst] Entry blocked | {blocked}")
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

        # Two pending limits at the same entry and stop, one per target — see
        # trendline's _place_market for why the split is two orders. Both are
        # ORDER_TIME_DAY, so an unfilled pair expires together as before.
        legs: list[tuple[float, float]]      # (lots, tp)
        split = None
        if signal.target_price_2 is not None:
            split = split_lots(lots, self._cfg.tp1_fraction,
                               sym_info.volume_min, sym_info.volume_step)
            if split is None:
                logger.info(
                    f"[SB] Split skipped | {lots:.2f} lots cannot divide into two legs at or "
                    f"above volume_min={sym_info.volume_min} (step={sym_info.volume_step}) — "
                    f"placing one undivided limit at TP1"
                )
        if split is not None:
            legs = [(split[0], signal.target_price), (split[1], signal.target_price_2)]
        else:
            legs = [(lots, signal.target_price)]

        for leg_no, (leg_lots, tp) in enumerate(legs, start=1):
            request = {
                "action":       mt5.TRADE_ACTION_PENDING,
                "symbol":       symbol,
                "volume":       leg_lots,
                "type":         order_type,
                "price":        round(signal.entry_price, d),
                "sl":           round(signal.stop_price,  d),
                "tp":           round(tp, d),
                "deviation":    20,
                "magic":        SB_MAGIC,
                "comment":      f"SilverBullet_TP{leg_no}" if len(legs) > 1 else "SilverBullet",
                "type_time":    mt5.ORDER_TIME_DAY,    # auto-expires if still pending at day end
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }

            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self._pending[result.order] = _PendingOrder(signal=signal, is_off_hours=is_off_hours)
                leg_txt = f" leg{leg_no}/{len(legs)}" if len(legs) > 1 else ""
                logger.info(
                    f"[SB] LIMIT {signal.direction.upper()}{leg_txt} | {symbol} | "
                    f"Lots={leg_lots:.2f} | Entry={self._px(signal.entry_price)} "
                    f"SL={self._px(signal.stop_price)} TP={self._px(tp)} "
                    f"| #{result.order}"
                )
            else:
                logger.error(
                    f"[SB] Limit order failed (leg {leg_no}/{len(legs)}) | "
                    f"code={result.retcode} | {result.comment}"
                )

    def _place_market(self, symbol: str, signal: Signal, lots: float, is_off_hrs: bool) -> None:
        from src.logger import logger

        if self._cfg.skip_news_days and is_news_day(datetime.now(NY_TZ).date()):
            logger.warning("[SB] Market order blocked — high-impact news day")
            return

        from news_analyst import reject_entry
        blocked = reject_entry(symbol, signal.direction)
        if blocked:
            logger.info(f"[Analyst] Entry blocked | {blocked}")
            return

        if not self._validate_symbol(symbol):
            return

        sym_info = mt5_cache.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[SB] Symbol {symbol} not found")
            return
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5_cache.symbol_info_tick(symbol)
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
                f"[SB] Signal stale | Price={self._px(price)} Entry={self._px(signal.entry_price)} "
                f"slip={entry_slip:.1f}pts (risk={risk_pts:.1f}pts) — skipping market entry"
            )
            return

        # Enforce broker minimum stop distance from the relevant market price.
        min_dist = sym_info.trade_stops_level * sym_info.point
        sl = signal.stop_price
        if is_long:
            if stop_price - sl < min_dist:
                sl = round(stop_price - min_dist * 1.1, d)
        else:
            if sl - stop_price < min_dist:
                sl = round(stop_price + min_dist * 1.1, d)

        def clamp_tp(tp: float) -> float:
            if is_long:
                return round(stop_price + min_dist * 1.1, d) if tp - stop_price < min_dist else tp
            return round(stop_price - min_dist * 1.1, d) if stop_price - tp < min_dist else tp

        logger.debug(
            f"[SB] Broker min_dist={min_dist:.1f} | "
            f"SL adjusted: {self._px(signal.stop_price)}→{self._px(sl)} | "
            f"TP adjusted: {self._px(signal.target_price)}→{self._px(clamp_tp(signal.target_price))}"
        )

        # Two independent positions sharing one SL — see trendline's
        # _place_market for why this is two orders rather than a partial close.
        legs: list[tuple[float, float]]      # (lots, tp)
        split = None
        if signal.target_price_2 is not None:
            split = split_lots(lots, self._cfg.tp1_fraction,
                               sym_info.volume_min, sym_info.volume_step)
            if split is None:
                logger.info(
                    f"[SB] Split skipped | {lots:.2f} lots cannot divide into two legs at or "
                    f"above volume_min={sym_info.volume_min} (step={sym_info.volume_step}) — "
                    f"placing one undivided order at TP1"
                )
        if split is not None:
            legs = [(split[0], clamp_tp(signal.target_price)),
                    (split[1], clamp_tp(signal.target_price_2))]
        else:
            legs = [(lots, clamp_tp(signal.target_price))]

        for leg_no, (leg_lots, tp) in enumerate(legs, start=1):
            result = mt5.order_send({
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       leg_lots,
                "type":         order_type,
                "price":        round(price, d),
                "sl":           sl,
                "tp":           tp,
                "deviation":    20,
                "magic":        SB_MAGIC,
                "comment":      f"SilverBullet_MKT_TP{leg_no}" if len(legs) > 1 else "SilverBullet_MKT",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logger.error(
                    f"[SB] Market order failed (leg {leg_no}/{len(legs)}) | "
                    f"code={result.retcode} | {result.comment}"
                )
                continue

            # Read straight from MT5, not the snapshot: this position did not
            # exist when the tick's snapshot was taken.
            mt5_cache.invalidate_positions()
            positions = mt5.positions_get(ticket=result.order) or []
            fill_price = positions[0].price_open if positions else price
            self._open[result.order] = _OpenPosition(
                signal=signal,
                fill_price=fill_price,
                is_off_hours=is_off_hrs,
            )
            if is_off_hrs:
                self._off_hours_fills += 1
            record_ticket(result.order, strategy="SB")
            leg_txt = f" leg{leg_no}/{len(legs)}" if len(legs) > 1 else ""
            logger.info(
                f"[SB] MARKET {signal.direction.upper()}{leg_txt} | {symbol} | "
                f"Lots={leg_lots:.2f} | Fill={self._px(fill_price)} "
                f"SL={self._px(sl)} TP={self._px(tp)} | #{result.order}"
            )

    def _cancel_pending(self, ticket: int) -> None:
        if ticket not in self._pending:
            return
        from src.logger import logger

        result = mt5.order_send({
            "action": mt5.TRADE_ACTION_REMOVE,
            "order":  ticket,
        })
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[SB] Pending #{ticket} cancelled (window ended)")
        else:
            logger.warning(
                f"[SB] Cancel failed | code={result.retcode} | {result.comment}"
            )
        self._pending.pop(ticket, None)

    def _time_exit(self, symbol: str, ticket: int) -> None:
        if ticket not in self._open:
            return
        from src.logger import logger

        positions = mt5_cache.positions_get(ticket=ticket)
        if not positions:
            del self._open[ticket]
            return

        pos  = positions[0]
        tick = mt5_cache.symbol_info_tick(symbol)
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
            mt5_cache.invalidate_positions()
            logger.info(f"[SB] Time exit | #{pos.ticket} | PnL ${pos.profit:.2f}")
            del self._open[ticket]
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

    def _boost_active(self) -> bool:
        """True once NY time has passed DAILY_TRADE_FLOOR_TIME_ET and the
        combined SB+TL trade count today (set by bot.py each loop tick) is
        still below DAILY_TRADE_FLOOR. Never fabricates a trade — callers
        use this to widen an already-passing signal's tolerances, not to
        invent one."""
        threshold = getattr(root_config, "DAILY_TRADE_FLOOR_TIME_ET", "14:00")
        floor = getattr(root_config, "DAILY_TRADE_FLOOR", 3)
        h, m = map(int, threshold.split(":"))
        past_threshold = datetime.now(NY_TZ).time() >= dtime(h, m)
        active = past_threshold and self.combined_daily_trades < floor

        if active and not self._boost_notified:
            from src.logger import logger
            logger.info(
                f"[SB] Adaptive floor | {self.combined_daily_trades}/{floor} trades by "
                f"{threshold} ET — relaxing entry filters for the rest of today"
            )
            self._boost_notified = True
        if not active:
            self._boost_notified = False

        return active

    def _boosted_cfg(self, base: SilverBulletConfig) -> SilverBulletConfig:
        """Relax entry filters on top of whatever base config is already in
        effect (aggressive/off-hours). Halves the minimum-risk and FVG-size
        floors rather than removing them, so a setup still has to clear a
        real (if lower) bar — this only widens which genuine signals
        qualify, it never fabricates one.

        No absolute floor is applied. `base` already carries this symbol's
        volatility-scaled thresholds from SB_TARGETS, so a raw `max(1.0, ...)`
        guard here is not a safety net — it is a US30-sized constant that
        exceeds any achievable stop distance on FX. EURUSDm's median M5 bar is
        0.00028; a 1.0 floor rejected every boosted signal on EURUSDm and
        GBPUSDm, turning the trade-floor booster into a total block for the
        two symbols it was most needed on."""
        return _dc_replace(
            base,
            min_risk_points=base.min_risk_points * 0.5,
            fvg_min_points=base.fvg_min_points * 0.5,
        )

    def _stop_inside_spread(self, symbol: str, signal: Signal) -> bool:
        """True when the stop is too close to the entry to survive the spread.

        A long fills at ask and is stopped when bid reaches the SL, so a stop
        nearer than the spread is already breached at the moment of fill. The
        loss is certain, and sizing makes it worse: risk is divided by that
        same small distance, so the doomed trade asks for the largest position.

        Reads `self._cfg`, not the effective (off-hours / boosted) config, on
        purpose. `_boosted_cfg` halves `min_risk_points` to widen which real
        setups qualify — a defensible frequency trade-off — but nothing should
        be able to relax a floor that exists because the arithmetic of the fill
        makes the trade unwinnable.
        """
        from src.logger import logger

        mult = self._cfg.min_stop_spread_mult
        if mult <= 0:
            return False

        tick = mt5_cache.symbol_info_tick(symbol)
        if tick is None:
            return False
        spread = tick.ask - tick.bid
        if spread <= 0:
            return False

        risk = abs(signal.entry_price - signal.stop_price)
        if risk >= spread * mult:
            return False

        logger.warning(
            f"[SB] Signal rejected | stop {self._px(risk)} from entry is inside "
            f"{mult}x the spread {self._px(spread)} — would be stopped on fill | "
            f"entry={self._px(signal.entry_price)} stop={self._px(signal.stop_price)}"
        )
        return True

    def _compute_lots(self, symbol: str, signal: Signal) -> Optional[float]:
        from src.logger import logger

        sym_info = mt5_cache.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[SB] No symbol info for {symbol}")
            return None

        account = mt5_cache.account_info()
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

        # Clamp SB_RISK_PCT (or this instance's override share of it) to a
        # sane range.  On accounts under $200 also enforce a 2% ceiling so a
        # misconfigured env var cannot blow up a micro account in one trade.
        base_risk_pct = (
            self._risk_pct_override if self._risk_pct_override is not None
            else float(root_config.SB_RISK_PCT)
        )
        risk_pct = max(0.01, min(base_risk_pct, 100.0))
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
        lots = max(sym_info.volume_min, min(lots, sym_info.volume_max, 8.0))

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

        logger.debug(
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
        from datetime import datetime
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
        # deal.time (like bar/tick time) is stamped in the broker's server
        # clock, so the from/to boundaries must be expressed in that same clock
        # — mt5_cache shifts our true-UTC boundaries by the measured broker
        # offset rather than a hardcoded guess, and fetches the window once per
        # loop tick for all three strategies instead of once per adapter.
        try:
            deals = mt5_cache.history_deals_today(self._broker_utc_offset, NY_TZ)
        except Exception as exc:
            logger.warning(f"[SB] Failed to fetch history deals: {exc}")
            deals = []

        # Some brokers (e.g. AtlasFunded-Server) zero out `magic` on deals,
        # so magic alone can't be trusted to attribute deals back to this
        # strategy — fall back to the locally recorded ticket numbers SB
        # itself confirmed opening (see src/ticket_store.py).
        own_tickets = load_tickets(strategy="SB")

        daily_pnl = 0.0
        daily_entries = 0
        for deal in deals:
            # Scope to this instance's own symbol first — with multiple SB
            # instances trading different symbols under the shared SB_MAGIC,
            # magic/own_tickets alone would pool every symbol's deals into
            # one count, silently applying one instance's daily cap to all.
            if deal.symbol != symbol:
                continue
            if deal.magic != SB_MAGIC and deal.position_id not in own_tickets:
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

        account = mt5_cache.account_info()
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
            for ticket in list(self._pending):
                self._cancel_pending(ticket)
            for ticket in list(self._open):
                self._time_exit(symbol, ticket)
            return False

        return True
