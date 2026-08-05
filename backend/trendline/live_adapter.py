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
- Multiple open positions can be live at once, each tracked by its own MT5
  ticket in `_open` — see cfg.one_trade_at_a_time (default False) in
  trendline/config.py. The only throttle on how many trades happen in a day
  is TL_MAX_TRADES_PER_DAY (enforced in _check_daily_limits).
- Magic number 202411001 is reserved for the Trendline strategy (distinct
  from Silver Bullet's SB_MAGIC = 202406122).
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

from .config import TrendlineConfig
from .strategy import Signal, SignalGenerator

NY_TZ = ZoneInfo("America/New_York")
TL_MAGIC = 202411001


@dataclass
class _OpenPosition:
    """A filled position this adapter is managing (breakeven/trail)."""
    signal: Signal
    fill_price: float
    breakeven_triggered: bool = False
    trail_best_price: Optional[float] = None


class TrendlineLiveAdapter:
    """Stateful, bar-by-bar adapter. Instantiate once; call .cycle() every 5s."""

    # Trendline reads H1 bars — used by _idle_between_bars to tell whether a
    # new bar has closed without paying for a fetch to find out.
    _BAR_PERIOD_SEC = 3600

    def __init__(self, cfg: TrendlineConfig, symbol: Optional[str] = None,
                 risk_pct_override: Optional[float] = None):
        self._cfg = cfg
        self._generator = SignalGenerator(cfg)
        self._symbol: Optional[str] = symbol
        # When multiple instances of this strategy run concurrently on
        # different symbols, each is given a fraction of TL_RISK_PCT
        # (see bot.py) so total account risk stays comparable to a single
        # instance. None means "use TL_RISK_PCT directly".
        self._risk_pct_override: Optional[float] = risk_pct_override
        self._last_bar_time: Optional[pd.Timestamp] = None
        # Bar-period boundary this adapter last ran a full scan at, so an
        # idle adapter fetches bars once per H1 bar, not once per loop tick.
        self._last_bar_slot: Optional[int] = None
        # Open positions this adapter placed, keyed by MT5 ticket — a dict
        # rather than a single slot so several can be live at once when
        # cfg.one_trade_at_a_time is False (see module docstring).
        self._open: dict[int, _OpenPosition] = {}
        self._initialized: bool = False
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cycle(self, symbol: str) -> None:
        """Called from the main bot loop. Manages the full lifecycle of one
        trendline setup."""
        from src.logger import logger

        logger.debug(
            f"[TL] Cycle start | symbol={symbol} | initialized={self._initialized} | "
            f"open={list(self._open)}"
        )

        if not self._validate_symbol(symbol):
            logger.debug("[TL] Cycle aborted | symbol validation failed")
            return

        # MT5 timestamps (bars, ticks, deals) are stamped in the broker's own
        # server clock, not true UTC — measure the current offset once per
        # cycle so every date/daily-count calc below can correct for it.
        # See src/broker_time.py.
        self._broker_utc_offset = mt5_cache.broker_utc_offset(symbol)

        if self._drawdown_halted:
            logger.debug("[TL] Cycle skipped | drawdown circuit breaker active")
            return
        if not self._check_drawdown_floor(symbol):
            logger.debug("[TL] Cycle skipped | drawdown floor breached")
            return

        # Daily entry cap: this only gates NEW entries later in the cycle —
        # positions already open are still synced and managed below
        # regardless, so reaching the cap never leaves an open trade without
        # breakeven/trailing for the rest of the day.
        can_enter_new = self._check_daily_limits(symbol)

        # With nothing on the books and no newly-closed bar, everything
        # below can only re-derive facts this adapter already holds — see
        # _idle_between_bars.
        if self._idle_between_bars():
            logger.debug("[TL] Cycle skipped | idle, no new H1 bar since last scan")
            return

        bars = self._fetch_bars(symbol, n=self._cfg.bars_lookback)
        if bars is None or len(bars) < 10:
            if not self._market_is_open(symbol):
                logger.debug(f"[TL] Market closed for {symbol} — waiting for reopen")
            else:
                logger.warning(f"[TL] Bar fetch failed for {symbol}")
            return

        # Bars come back timestamped in the broker's server clock (labeled
        # "UTC" but not actually true UTC on some brokers) — correct to true
        # UTC before any date/session math is done on them.
        bars.index = bars.index - self._broker_utc_offset

        # Drop the currently-forming (incomplete) bar
        completed = bars.iloc[:-1]
        if completed.empty:
            logger.debug("[TL] Cycle skipped | no completed bars available")
            return

        # Bars are in hand, so this bar period counts as scanned regardless of
        # what the rest of the cycle decides. Marking it here rather than in
        # the gate means a failed or empty fetch above retries on the next
        # tick instead of waiting out a whole bar.
        self._mark_bar_scanned()

        logger.debug(
            f"[TL] Bars fetched | total={len(bars)} completed={len(completed)} | "
            f"first={completed.index[0]} UTC | last={completed.index[-1]} UTC"
        )

        times  = completed.index.tolist()
        highs  = completed["high"].to_numpy(dtype=float)
        lows   = completed["low"].to_numpy(dtype=float)
        closes = completed["close"].to_numpy(dtype=float)
        opens  = completed["open"].to_numpy(dtype=float)

        today_ny = datetime.now(NY_TZ).date().isoformat()

        # News-day circuit breaker: no new entries on high-impact macro days.
        # Existing positions are still managed below (not flattened) — this
        # only blocks new entries, matching Silver Bullet's off-hours flow.
        from silver_bullet.news_calendar import is_news_day
        news_skip = self._cfg.skip_news_days and is_news_day(today_ny)
        if news_skip and self._news_skip_date != today_ny:
            logger.info(f"[TL] News day {today_ny} — trading paused for high-impact macro releases")
            self._news_skip_date = today_ny

        # 1. Detect positions MT5 already closed externally (SL/TP hit)
        self._sync_position(symbol)

        # 2. Manage every open position (breakeven/trail). Runs even if the
        #    daily cap or a news day is blocking new entries.
        for ticket in list(self._open):
            pos = self._open.get(ticket)
            if pos is None:
                continue
            positions = mt5_cache.positions_get(ticket=ticket)
            if positions:
                live = positions[0]
                side = "LONG" if live.type == mt5.ORDER_TYPE_BUY else "SHORT"
                logger.debug(
                    f"[TL] Position status | #{live.ticket} | {side} | "
                    f"Price={live.price_current:.5f} | P&L=${live.profit:+.2f}"
                )
            self._check_breakeven(symbol, ticket)

        if not can_enter_new or news_skip:
            logger.debug("[TL] Cycle end | new entries blocked")
            return

        # 3. Feed unprocessed bars through the signal generator
        latest_idx = len(times) - 1
        processed_count = 0
        signal_count = 0
        boost_active = self._boost_active()
        original_cfg = self._generator._cfg
        if boost_active:
            self._generator._cfg = self._boosted_cfg(original_cfg)
        try:
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
                        logger.debug(
                            f"[TL] Signal skipped | init warmup | bar={i} latest={latest_idx}"
                        )
                        continue
                    lots = self._compute_lots(symbol, signal)
                    if lots is not None:
                        logger.info(
                            f"[TL] About to place order | {signal.direction.upper()} | "
                            f"entry={signal.entry_price:.5f} stop={signal.stop_price:.5f} "
                            f"target={signal.target_price:.5f} | lots={lots:.2f}"
                        )
                        self._place_market(symbol, signal, lots)
                    break  # one new order per cycle
                elif signal is not None:
                    logger.debug(
                        f"[TL] Signal skipped | init={self._initialized} | "
                        f"date={date_str} today={today_ny}"
                    )
        finally:
            self._generator._cfg = original_cfg

        logger.debug(
            f"[TL] Signal scan complete | processed={processed_count} | "
            f"signals_found={signal_count}"
        )
        # Routine heartbeat for the dashboard's Scanner persona: fires once
        # per newly-closed bar, not every cycle tick, so the feed reads as
        # periodic status rather than spam.
        if processed_count > 0 and signal_count == 0:
            logger.info(
                f"[TL] No setup on {processed_count} new bar(s) | price={closes[-1]:.5f}"
            )

        if times:
            self._last_bar_time = times[-1]
        self._initialized = True
        logger.debug("[TL] Cycle end | watermark advanced | init=True")

    def shutdown(self, symbol: str) -> None:
        """Close all open positions on shutdown."""
        for ticket in list(self._open):
            self._time_exit(symbol, ticket)

    # ------------------------------------------------------------------
    # MT5 operations
    # ------------------------------------------------------------------

    def _fetch_bars(self, symbol: str, n: int) -> Optional[pd.DataFrame]:
        if not mt5_cache.symbol_info(symbol):
            mt5.symbol_select(symbol, True)
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, n)
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[["open", "high", "low", "close"]]

    def _idle_between_bars(self) -> bool:
        """True when this cycle provably has nothing to do and can be skipped.

        The bot loop ticks every 5 seconds but Trendline reads H1 bars, so 719 of
        every 720 cycles re-fetch cfg.bars_lookback bars that cannot contain anything new.

        Skipping is only safe when nothing else in the cycle can act: with no
        open position there is no breakeven, trailing stop or exit to manage,
        and with no newly-closed bar there is no new price action to feed the
        generator. Under those conditions the rest of the cycle reads bars,
        iterates an empty dict and re-derives what it already holds, so
        skipping changes no decision this adapter would make.

        Bar arrival is derived from the clock rather than from a fetch (which
        is the cost being avoided): the in-progress bar opens at the current
        hour boundary, so a new bar has closed exactly when that boundary
        moves. Tracking the boundary last scanned at — rather than comparing
        against `_last_bar_time` — also keeps this correct when the market is
        closed and no new bars arrive, which would otherwise leave the
        watermark stuck and refetch on every tick.

        This is a pure predicate: the boundary is only marked scanned once a
        fetch has actually succeeded (see `_mark_bar_scanned`), so a failed or
        empty fetch retries on the next tick rather than waiting out a bar.
        """
        if self._open:
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
        """Best-effort check whether the symbol is currently tradeable."""
        from datetime import timezone

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

    def _sync_position(self, symbol: str) -> None:
        """Drop any open position MT5 has already closed via SL or TP, and
        notify the generator once nothing is left open (lifts the
        one-trade-at-a-time gate, when that mode is enabled)."""
        if not self._open:
            return
        from src.logger import logger
        for ticket in list(self._open):
            positions = mt5_cache.positions_get(ticket=ticket)
            if not positions:
                logger.info(f"[TL] Position #{ticket} closed by MT5 (SL/TP)")
                del self._open[ticket]
        if not self._open:
            self._generator.notify_trade_closed()

    def _check_breakeven(self, symbol: str, ticket: int) -> None:
        """Move stop to entry at breakeven_r; then trail at trail_r beyond that."""
        pos = self._open.get(ticket)
        if pos is None:
            return

        tick = mt5_cache.symbol_info_tick(symbol)
        if tick is None:
            return

        from src.logger import logger

        cfg      = self._cfg
        sig      = pos.signal
        fill     = pos.fill_price
        risk_pts = abs(fill - sig.stop_price)
        is_long  = sig.direction == "long"
        current_px = tick.bid if is_long else tick.ask

        # Phase 1 — breakeven
        if not pos.breakeven_triggered and cfg.breakeven_r > 0:
            trigger_dist = risk_pts * cfg.breakeven_r
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
                d        = sym_info.digits if sym_info else 5
                result   = mt5.order_send({
                    "action":   mt5.TRADE_ACTION_SLTP,
                    "symbol":   symbol,
                    "position": live.ticket,
                    "sl":       round(fill, d),
                    "tp":       round(live.tp, d),
                })
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    # The trailing phase below re-reads this position to
                    # compare against its current SL — drop the snapshot so
                    # it sees the stop we just moved, not the older one.
                    mt5_cache.invalidate_positions()
                    pos.breakeven_triggered = True
                    logger.debug(
                        f"[TL] Breakeven triggered | #{live.ticket} | SL moved to {fill:.5f}"
                    )

        # Phase 2 — trailing stop (only after breakeven)
        if pos.breakeven_triggered and cfg.trail_r > 0:
            if is_long:
                if pos.trail_best_price is None or current_px > pos.trail_best_price:
                    pos.trail_best_price = current_px
                new_sl = pos.trail_best_price - risk_pts * cfg.trail_r
            else:
                if pos.trail_best_price is None or current_px < pos.trail_best_price:
                    pos.trail_best_price = current_px
                new_sl = pos.trail_best_price + risk_pts * cfg.trail_r

            positions = mt5_cache.positions_get(ticket=ticket)
            if not positions:
                return
            live     = positions[0]
            sym_info = mt5_cache.symbol_info(symbol)
            d        = sym_info.digits if sym_info else 5
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
                        f"[TL] Trail stop updated | #{live.ticket} | SL moved to {new_sl:.5f}"
                    )

    def _place_market(self, symbol: str, signal: Signal, lots: float) -> None:
        from src.logger import logger

        if not self._validate_symbol(symbol):
            return

        sym_info = mt5_cache.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[TL] Symbol {symbol} not found")
            return
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5_cache.symbol_info_tick(symbol)
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

        # A split becomes two independent MT5 positions sharing one SL: the
        # first carries TP1, the second TP2, and _manage_positions trails each
        # ticket separately (it reads every ticket's own tp back from MT5).
        # Two orders rather than one partial-close because the adapter already
        # tracks positions by ticket and never has to watch for a fill mid-bar.
        legs: list[tuple[float, float]]      # (lots, tp)
        split = None
        if signal.target_price_2 is not None:
            split = split_lots(lots, self._cfg.tp1_fraction,
                               sym_info.volume_min, sym_info.volume_step)
            if split is None:
                logger.info(
                    f"[TL] Split skipped | {lots:.2f} lots cannot divide into two legs at or "
                    f"above volume_min={sym_info.volume_min} (step={sym_info.volume_step}) — "
                    f"placing one undivided order at TP1"
                )
        if split is not None:
            legs = [(split[0], clamp_tp(signal.target_price)),
                    (split[1], clamp_tp(signal.target_price_2))]
        else:
            legs = [(lots, clamp_tp(signal.target_price))]

        placed = 0
        for leg_no, (leg_lots, tp) in enumerate(legs, start=1):
            result = mt5.order_send({
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       leg_lots,
                "type":         order_type,
                "price":        round(price, d),
                "sl":           round(sl, d),
                "tp":           round(tp, d),
                "deviation":    20,
                "magic":        TL_MAGIC,
                "comment":      f"Trendline_MKT_TP{leg_no}" if len(legs) > 1 else "Trendline_MKT",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                # Read straight from MT5, not the snapshot: this position did
                # not exist when the tick's snapshot was taken.
                mt5_cache.invalidate_positions()
                positions = mt5.positions_get(ticket=result.order) or []
                fill_price = positions[0].price_open if positions else price
                self._open[result.order] = _OpenPosition(
                    signal=signal,
                    fill_price=fill_price,
                )
                record_ticket(result.order, strategy="TL")
                placed += 1
                leg_txt = f" leg{leg_no}/{len(legs)}" if len(legs) > 1 else ""
                logger.info(
                    f"[TL] MARKET {signal.direction.upper()}{leg_txt} | {symbol} | "
                    f"Lots={leg_lots:.2f} | Fill={fill_price:.5f} "
                    f"SL={sl:.5f} TP={tp:.5f} | pattern={signal.pattern} | #{result.order}"
                )
            else:
                logger.error(
                    f"[TL] Market order failed (leg {leg_no}/{len(legs)}) | "
                    f"code={result.retcode} | {result.comment}"
                )

        # Gate on whether anything actually opened, not on how many legs did:
        # a filled leg 1 with a rejected leg 2 is still a live position, and
        # leaving the generator un-gated would let it stack another setup on top.
        if placed:
            self._generator.notify_trade_opened()

    def _time_exit(self, symbol: str, ticket: int) -> None:
        if ticket not in self._open:
            return
        from src.logger import logger

        positions = mt5_cache.positions_get(ticket=ticket)
        if not positions:
            del self._open[ticket]
            if not self._open:
                self._generator.notify_trade_closed()
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
            "magic":        TL_MAGIC,
            "comment":      "TL_shutdown_exit",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            mt5_cache.invalidate_positions()
            logger.info(f"[TL] Shutdown exit | #{pos.ticket} | PnL ${pos.profit:.2f}")
            del self._open[ticket]
            if not self._open:
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
                f"[TL] Adaptive floor | {self.combined_daily_trades}/{floor} trades by "
                f"{threshold} ET — relaxing entry filters for the rest of today"
            )
            self._boost_notified = True
        if not active:
            self._boost_notified = False

        return active

    def _boosted_cfg(self, base: TrendlineConfig) -> TrendlineConfig:
        """Relax entry filters once the adaptive daily-trade floor has
        kicked in. Halves the minimum-risk floor and widens touch/steepness
        tolerances rather than removing them, so a setup still has to clear
        a real (if lower) bar — this only widens which genuine signals
        qualify, it never fabricates one.

        No absolute floor is applied. `base` already carries this symbol's
        volatility-scaled thresholds from TL_TARGETS, so a raw `max(3.0, ...)`
        guard here is not a safety net — it is a US30-sized constant that
        exceeds any achievable stop distance on FX. USDJPYm's median H1 bar is
        0.147, so a 3.0 floor is ~20x a whole bar: every boosted signal on the
        highest-frequency TL symbol was rejected from 14:00 ET onward on any
        day quiet enough for the booster to engage."""
        return _dc_replace(
            base,
            min_risk_points=base.min_risk_points * 0.5,
            touch_tolerance_points=base.touch_tolerance_points * 1.5,
            steepness_max_ratio=base.steepness_max_ratio * 1.5,
        )

    def _compute_lots(self, symbol: str, signal: Signal) -> Optional[float]:
        from src.logger import logger

        sym_info = mt5_cache.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[TL] No symbol info for {symbol}")
            return None

        account = mt5_cache.account_info()
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

        base_risk_pct = (
            self._risk_pct_override if self._risk_pct_override is not None
            else float(getattr(root_config, "TL_RISK_PCT", 1.0))
        )
        risk_pct = max(0.01, min(base_risk_pct, 100.0))
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

        logger.debug(
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
        from datetime import timezone
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

        # deal.time (like bar/tick time) is stamped in the broker's server
        # clock, so the from/to boundaries must be expressed in that same clock
        # — mt5_cache shifts our true-UTC boundaries by the measured broker
        # offset rather than a hardcoded guess, and fetches the window once per
        # loop tick for all three strategies instead of once per adapter.
        try:
            deals = mt5_cache.history_deals_today(self._broker_utc_offset, NY_TZ)
        except Exception as exc:
            logger.warning(f"[TL] Failed to fetch history deals: {exc}")
            deals = []

        # Some brokers (e.g. AtlasFunded-Server) zero out `magic` on deals,
        # so magic alone can't be trusted to attribute deals back to this
        # strategy — fall back to the locally recorded ticket numbers TL
        # itself confirmed opening (see src/ticket_store.py).
        own_tickets = load_tickets(strategy="TL")

        daily_pnl = 0.0
        daily_entries = 0
        for deal in deals:
            # Scope to this instance's own symbol first — with multiple TL
            # instances trading different symbols under the shared TL_MAGIC,
            # magic/own_tickets alone would pool every symbol's deals into
            # one count, silently applying one instance's daily cap to all.
            if deal.symbol != symbol:
                continue
            if deal.magic != TL_MAGIC and deal.position_id not in own_tickets:
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

        account = mt5_cache.account_info()
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
            for ticket in list(self._open):
                self._time_exit(symbol, ticket)
            return False

        return True
