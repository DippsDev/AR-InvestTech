"""
Mutanabby live adapter: connects the SuperTrend flip engine to MT5.

On each call to .cycle(symbol):
  1. Fetch the last cfg.bars_lookback H1 bars from MT5 and drop the forming one
  2. Rebuild the SignalGenerator over that window and read the latest bar
  3. On a new Signal: place a market order with SL and TP pre-set
  4. MT5 manages SL/TP once the position is open; breakeven/trail if configured

Design notes
------------
- Mirrors trendline/live_adapter.py's structure, idioms and safety rails
  (broker-clock correction, drawdown breaker, daily caps, stale-signal guard,
  small-account sizing caps). trendline/*.py and silver_bullet/*.py are not
  modified by this module.
- Magic number 202507001 is reserved for Mutanabby, distinct from Silver
  Bullet's SB_MAGIC = 202406122 and Trendline's TL_MAGIC = 202411001.

Two deliberate differences from the Trendline adapter
-----------------------------------------------------
1. *Only the newest completed bar is examined*, not every unprocessed bar.
   Trendline must replay bars because its SignalGenerator accumulates
   trendline state across calls. Mutanabby's does not: it precomputes every
   series in its constructor, so a rebuilt generator over the same window
   yields byte-identical signals. Replaying older bars would therefore only
   risk acting on stale ones.

   The window is safe to rebuild from: SuperTrend is recursive, but its band
   ratchet resets on every direction flip, so state converges. Measured on
   8,260 H1 US30 bars, a rolling window reproduces full-history signals with
   0 mismatches at >=150 bars — cfg.bars_lookback of 300 leaves 2x margin.
   Below ~100 bars mismatches appear, so do not lower it.

2. *No adaptive daily-trade-floor boost.* Trendline widens its tolerances late
   in the day to clear DAILY_TRADE_FLOOR. Mutanabby has no equivalent knob:
   its only entry parameter is `sensitivity`, and changing that does not widen
   an existing signal's tolerance — it recomputes the SuperTrend and produces a
   *different* set of signals. That would fabricate trades rather than admit
   marginal ones, which is exactly what the boost is documented not to do.
   `combined_daily_trades` is still accepted for interface parity with bot.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import pandas as pd

import config as root_config

from src import mt5_cache
from src.split_target import split_lots
from src.ticket_store import load_tickets, record_ticket

from .config import MutanabbyConfig
from .strategy import Signal, SignalGenerator

NY_TZ = ZoneInfo("America/New_York")
MB_MAGIC = 202507001

# Below this many bars the SuperTrend band ratchet has not converged and live
# signals can diverge from the backtest. See the module docstring.
MIN_CONVERGENCE_BARS = 150


@dataclass
class _OpenPosition:
    """A filled position this adapter is managing (breakeven/trail)."""
    signal: Signal
    fill_price: float
    breakeven_triggered: bool = False
    trail_best_price: Optional[float] = None


class MutanabbyLiveAdapter:
    """Stateful, bar-by-bar adapter. Instantiate once; call .cycle() every 5s."""

    # Mutanabby reads H1 bars — used by _idle_between_bars to tell whether a
    # new bar has closed without paying for a fetch to find out.
    _BAR_PERIOD_SEC = 3600

    def __init__(self, cfg: MutanabbyConfig, symbol: Optional[str] = None,
                 risk_pct_override: Optional[float] = None):
        self._cfg = cfg
        self._symbol: Optional[str] = symbol
        # When multiple instances of this strategy run concurrently on
        # different symbols, each is given a fraction of MB_RISK_PCT (see
        # bot.py). None means "use MB_RISK_PCT directly".
        self._risk_pct_override: Optional[float] = risk_pct_override
        self._last_bar_time: Optional[pd.Timestamp] = None
        # Bar-period boundary this adapter last ran a full scan at, so an
        # idle adapter fetches bars once per H1 bar, not once per loop tick.
        self._last_bar_slot: Optional[int] = None
        # Open positions this adapter placed, keyed by MT5 ticket.
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
        # Broker/trade-server clock offset from true UTC, remeasured each cycle.
        self._broker_utc_offset: timedelta = timedelta(0)
        # Set by bot.py each loop tick. Accepted for interface parity only —
        # Mutanabby has no boost mode (see module docstring).
        self.combined_daily_trades: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cycle(self, symbol: str) -> None:
        """Called from the main bot loop. Manages the full lifecycle of one
        Mutanabby setup."""
        from src.logger import logger

        logger.debug(
            f"[MB] Cycle start | symbol={symbol} | initialized={self._initialized} | "
            f"open={list(self._open)}"
        )

        if not self._validate_symbol(symbol):
            logger.debug("[MB] Cycle aborted | symbol validation failed")
            return

        # MT5 timestamps (bars, ticks, deals) are stamped in the broker's own
        # server clock, not true UTC — measure the current offset once per
        # cycle so every date/daily-count calc below can correct for it.
        self._broker_utc_offset = mt5_cache.broker_utc_offset(symbol)

        if self._drawdown_halted:
            logger.debug("[MB] Cycle skipped | drawdown circuit breaker active")
            return
        if not self._check_drawdown_floor(symbol):
            logger.debug("[MB] Cycle skipped | drawdown floor breached")
            return

        # Daily entry cap gates NEW entries only; open positions are still
        # synced and managed below so hitting the cap never strands a trade.
        can_enter_new = self._check_daily_limits(symbol)

        # With nothing on the books and no newly-closed bar, everything
        # below can only re-derive facts this adapter already holds — see
        # _idle_between_bars.
        if self._idle_between_bars():
            logger.debug("[MB] Cycle skipped | idle, no new H1 bar since last scan")
            return

        bars = self._fetch_bars(symbol, n=self._cfg.bars_lookback)
        if bars is None or len(bars) < MIN_CONVERGENCE_BARS:
            if not self._market_is_open(symbol):
                logger.debug(f"[MB] Market closed for {symbol} — waiting for reopen")
            elif bars is None:
                logger.warning(f"[MB] Bar fetch failed for {symbol}")
            else:
                # Not an error worth trading through: with too little history
                # the SuperTrend band ratchet has not converged, so any signal
                # here could differ from the backtested one.
                logger.warning(
                    f"[MB] Only {len(bars)} H1 bars for {symbol} — need "
                    f"{MIN_CONVERGENCE_BARS} for SuperTrend convergence; skipping"
                )
            return

        # Bars come back timestamped in the broker's server clock (labeled
        # "UTC" but not actually true UTC on some brokers) — correct before
        # any date math.
        bars.index = bars.index - self._broker_utc_offset

        # Drop the currently-forming (incomplete) bar. This is load-bearing for
        # this strategy in particular: the source indicator's own header admits
        # its signals appear and disappear while a bar is still forming, and
        # only the close is final.
        completed = bars.iloc[:-1]
        if len(completed) < MIN_CONVERGENCE_BARS:
            logger.debug("[MB] Cycle skipped | too few completed bars")
            return

        # Bars are in hand, so this bar period counts as scanned regardless of
        # what the rest of the cycle decides. Marking it here rather than in
        # the gate means a failed or empty fetch above retries on the next
        # tick instead of waiting out a whole bar.
        self._mark_bar_scanned()

        times = completed.index.tolist()
        highs = completed["high"].to_numpy(dtype=float)
        lows = completed["low"].to_numpy(dtype=float)
        closes = completed["close"].to_numpy(dtype=float)

        logger.debug(
            f"[MB] Bars fetched | total={len(bars)} completed={len(completed)} | "
            f"first={times[0]} UTC | last={times[-1]} UTC"
        )

        today_ny = datetime.now(NY_TZ).date().isoformat()

        # News-day circuit breaker: blocks new entries only; open positions
        # are still managed below (not flattened).
        from silver_bullet.news_calendar import is_news_day
        news_skip = self._cfg.skip_news_days and is_news_day(today_ny)
        if news_skip and self._news_skip_date != today_ny:
            logger.info(
                f"[MB] News day {today_ny} — trading paused for high-impact macro releases"
            )
            self._news_skip_date = today_ny

        # 1. Detect positions MT5 already closed externally (SL/TP hit)
        self._sync_position(symbol)

        # 2. Manage every open position (breakeven/trail). Runs even when the
        #    daily cap or a news day is blocking new entries.
        for ticket in list(self._open):
            if self._open.get(ticket) is None:
                continue
            positions = mt5_cache.positions_get(ticket=ticket)
            if positions:
                live = positions[0]
                side = "LONG" if live.type == mt5.ORDER_TYPE_BUY else "SHORT"
                logger.debug(
                    f"[MB] Position status | #{live.ticket} | {side} | "
                    f"Price={live.price_current:.5f} | P&L=${live.profit:+.2f}"
                )
            self._check_breakeven(symbol, ticket)

        if not can_enter_new or news_skip:
            logger.debug("[MB] Cycle end | new entries blocked")
            return

        # 3. Only the newest completed bar can produce a tradeable signal
        #    (see module docstring for why no replay is needed).
        latest_ts = times[-1]
        if self._last_bar_time is not None and latest_ts <= self._last_bar_time:
            logger.debug("[MB] Cycle end | no new completed bar")
            return

        generator = SignalGenerator(self._cfg, highs, lows, closes)
        # The generator is rebuilt every cycle, so its one-trade-at-a-time gate
        # must be restored from the adapter's own view of what is open.
        if self._open:
            generator.notify_trade_opened()

        latest_idx = len(times) - 1
        ts_ny = latest_ts.astimezone(NY_TZ)
        date_str = ts_ny.date().isoformat()

        signal = generator.on_bar(bar_idx=latest_idx, date_str=date_str)

        if signal is None:
            logger.info(
                f"[MB] No setup on bar {ts_ny:%Y-%m-%d %H:%M} ET | price={closes[-1]:.5f}"
            )
        elif date_str != today_ny:
            # Stale: the newest completed bar belongs to a previous session
            # (e.g. first cycle after a weekend).
            logger.debug(
                f"[MB] Signal skipped | bar date {date_str} is not today ({today_ny})"
            )
        elif not self._initialized:
            # First cycle after start-up: the newest bar may have closed long
            # before the bot came up, and its entry price is already gone.
            logger.info(
                f"[MB] Signal skipped | startup warmup | {signal.direction.upper()} "
                f"on {date_str}"
            )
        else:
            from news_analyst import reject_entry
            blocked = reject_entry(symbol, signal.direction, today_ny)
            if blocked:
                logger.info(f"[Analyst] Entry blocked | {blocked}")
            else:
                lots = self._compute_lots(symbol, signal)
                if lots is not None:
                    logger.info(
                        f"[MB] About to place order | {signal.direction.upper()} "
                        f"({signal.strength}) | entry={signal.entry_price:.5f} "
                        f"stop={signal.stop_price:.5f} target={signal.target_price:.5f} | "
                        f"lots={lots:.2f}"
                    )
                    self._place_market(symbol, signal, lots)

        self._last_bar_time = latest_ts
        self._initialized = True
        logger.debug("[MB] Cycle end | watermark advanced | init=True")

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

        The bot loop ticks every 5 seconds but Mutanabby reads H1 bars, so 719 of
        every 720 cycles re-fetch 300 bars that cannot contain anything new.

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
        # before measuring staleness.
        last_tick = datetime.fromtimestamp(tick.time, tz=timezone.utc) - self._broker_utc_offset
        age_sec = (datetime.now(tz=timezone.utc) - last_tick).total_seconds()
        return age_sec < 300  # 5 minutes

    def _sync_position(self, symbol: str) -> None:
        """Drop any open position MT5 has already closed via SL or TP."""
        if not self._open:
            return
        from src.logger import logger
        for ticket in list(self._open):
            positions = mt5_cache.positions_get(ticket=ticket)
            if not positions:
                logger.info(f"[MB] Position #{ticket} closed by MT5 (SL/TP)")
                del self._open[ticket]

    def _check_breakeven(self, symbol: str, ticket: int) -> None:
        """Move stop to entry at breakeven_r; then trail at trail_r beyond that.

        Both default to 0 in MutanabbyConfig — the backtested profit factors
        were measured with a flat stop-or-target ride, so this is inert unless
        deliberately enabled.
        """
        pos = self._open.get(ticket)
        if pos is None:
            return

        cfg = self._cfg
        if cfg.breakeven_r <= 0 and cfg.trail_r <= 0:
            return

        tick = mt5_cache.symbol_info_tick(symbol)
        if tick is None:
            return

        from src.logger import logger

        sig = pos.signal
        fill = pos.fill_price
        risk_pts = abs(fill - sig.stop_price)
        is_long = sig.direction == "long"
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
                live = positions[0]
                sym_info = mt5_cache.symbol_info(symbol)
                d = sym_info.digits if sym_info else 5
                result = mt5.order_send({
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
                        f"[MB] Breakeven triggered | #{live.ticket} | SL moved to {fill:.5f}"
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
            live = positions[0]
            sym_info = mt5_cache.symbol_info(symbol)
            d = sym_info.digits if sym_info else 5

            sl_improves = (new_sl > live.sl) if is_long else (new_sl < live.sl)
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
                        f"[MB] Trail stop updated | #{live.ticket} | SL moved to {new_sl:.5f}"
                    )

    def _place_market(self, symbol: str, signal: Signal, lots: float) -> None:
        from src.logger import logger
        from news_analyst import reject_entry

        blocked = reject_entry(symbol, signal.direction)
        if blocked:
            logger.info(f"[Analyst] Entry blocked | {blocked}")
            return

        if not self._validate_symbol(symbol):
            return

        sym_info = mt5_cache.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[MB] Symbol {symbol} not found")
            return
        if not sym_info.visible:
            mt5.symbol_select(symbol, True)

        tick = mt5_cache.symbol_info_tick(symbol)
        if tick is None:
            logger.error(f"[MB] No tick data for {symbol}")
            return

        is_long = signal.direction == "long"
        order_type = mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL

        price = tick.ask if is_long else tick.bid
        stop_price = tick.bid if is_long else tick.ask
        d = sym_info.digits

        # Skip stale signals — same 0.5R guard the backtester applies as
        # BacktestCosts.max_entry_slip_r, so live and backtest reject the same
        # entries. Measured on stored history this rejects ~0.05% of signals.
        risk_pts = abs(signal.entry_price - signal.stop_price)
        entry_slip = abs(price - signal.entry_price)
        if entry_slip > risk_pts * 0.5:
            logger.info(
                f"[MB] Signal stale | Price={price:.5f} Entry={signal.entry_price:.5f} "
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

        # Two independent positions sharing one SL — see trendline's
        # _place_market for why this is two orders rather than a partial close.
        legs: list[tuple[float, float]]      # (lots, tp)
        split = None
        if signal.target_price_2 is not None:
            split = split_lots(lots, self._cfg.tp1_fraction,
                               sym_info.volume_min, sym_info.volume_step)
            if split is None:
                logger.info(
                    f"[MB] Split skipped | {lots:.2f} lots cannot divide into two legs at or "
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
                "sl":           round(sl, d),
                "tp":           round(tp, d),
                "deviation":    20,
                "magic":        MB_MAGIC,
                "comment":      f"Mutanabby_MKT_TP{leg_no}" if len(legs) > 1 else "Mutanabby_MKT",
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
                record_ticket(result.order, strategy="MB")
                leg_txt = f" leg{leg_no}/{len(legs)}" if len(legs) > 1 else ""
                logger.info(
                    f"[MB] MARKET {signal.direction.upper()}{leg_txt} | {symbol} | "
                    f"Lots={leg_lots:.2f} | Fill={fill_price:.5f} SL={sl:.5f} TP={tp:.5f} | "
                    f"strength={signal.strength} | #{result.order}"
                )
            else:
                logger.error(
                    f"[MB] Market order failed (leg {leg_no}/{len(legs)}) | "
                    f"code={result.retcode} | {result.comment}"
                )

    def _time_exit(self, symbol: str, ticket: int) -> None:
        if ticket not in self._open:
            return
        from src.logger import logger

        positions = mt5_cache.positions_get(ticket=ticket)
        if not positions:
            del self._open[ticket]
            return

        pos = positions[0]
        tick = mt5_cache.symbol_info_tick(symbol)
        if tick is None:
            return

        is_buy = pos.type == mt5.ORDER_TYPE_BUY
        close_price = tick.bid if is_buy else tick.ask
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY

        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       pos.volume,
            "type":         close_type,
            "position":     pos.ticket,
            "price":        close_price,
            "deviation":    20,
            "magic":        MB_MAGIC,
            "comment":      "MB_shutdown_exit",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        })

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            mt5_cache.invalidate_positions()
            logger.info(f"[MB] Shutdown exit | #{pos.ticket} | PnL ${pos.profit:.2f}")
            del self._open[ticket]
        else:
            logger.error(
                f"[MB] Shutdown exit failed | code={result.retcode} | {result.comment}"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _validate_symbol(self, symbol: str) -> bool:
        """Guard against trading the wrong instrument."""
        from src.logger import logger

        if not symbol:
            logger.error("[MB] No symbol provided to adapter cycle — skipping")
            return False

        if self._symbol is not None and symbol != self._symbol:
            logger.error(
                f"[MB] Symbol mismatch | expected={self._symbol} received={symbol}. "
                f"Skipping cycle to avoid wrong-instrument execution."
            )
            return False

        return True

    def _compute_lots(self, symbol: str, signal: Signal) -> Optional[float]:
        from src.logger import logger

        sym_info = mt5_cache.symbol_info(symbol)
        if sym_info is None:
            logger.error(f"[MB] No symbol info for {symbol}")
            return None

        account = mt5_cache.account_info()
        if account is None:
            return None

        usable_capital = min(account.balance, account.equity)
        if usable_capital <= 0:
            logger.error("[MB] Account balance/equity is zero or negative — cannot size position")
            return None

        min_balance = getattr(root_config, "MB_MIN_BALANCE", 15.0)
        if usable_capital < min_balance:
            logger.warning(
                f"[MB] Usable capital ${usable_capital:.2f} is below the "
                f"configured minimum ${min_balance:.2f} — skipping trade"
            )
            return None

        base_risk_pct = (
            self._risk_pct_override if self._risk_pct_override is not None
            else float(getattr(root_config, "MB_RISK_PCT", 0.25))
        )
        risk_pct = max(0.01, min(base_risk_pct, 100.0))
        if usable_capital < 200.0:
            risk_pct = min(risk_pct, 2.0)

        risk_usd = usable_capital * (risk_pct / 100.0)

        small_acct_threshold = getattr(root_config, "MB_SMALL_ACCT_THRESHOLD", 150.0)
        max_risk_usd = getattr(root_config, "MB_MAX_RISK_USD", 1.0)
        if usable_capital < small_acct_threshold:
            capped_risk_usd = min(risk_usd, max_risk_usd)
            if capped_risk_usd < risk_usd:
                logger.info(
                    f"[MB] Small-account cap | Risk reduced from ${risk_usd:.2f} "
                    f"to ${capped_risk_usd:.2f} (balance below ${small_acct_threshold:.0f})"
                )
            risk_usd = capped_risk_usd

        risk_pts = abs(signal.entry_price - signal.stop_price)
        tick_val = sym_info.trade_tick_value
        tick_size = sym_info.trade_tick_size

        if risk_pts <= 0 or tick_val <= 0 or tick_size <= 0:
            logger.warning(
                f"[MB] Invalid sizing inputs: risk_pts={risk_pts}, "
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
                f"[MB] Sizing overshoot: {lots} lots would risk "
                f"${actual_risk_usd:.2f} ({actual_risk_usd / usable_capital * 100:.1f}% "
                f"of capital). Skipping trade."
            )
            return None

        logger.debug(
            f"[MB] Sizing | Capital=${usable_capital:.2f} RiskPct={risk_pct:.2f}% "
            f"Risk=${risk_usd:.2f} SL={risk_pts:.5f} RawLots={raw:.3f} "
            f"FinalLots={lots:.2f} TickVal={tick_val:.5f}/TickSize={tick_size}"
        )
        return round(lots, 2)

    def _check_daily_limits(self, symbol: str) -> bool:
        """Return True if new trades are allowed today.

        Enforces MB_DAILY_LOSS_LIMIT_USD and MB_MAX_TRADES_PER_DAY by querying
        MT5 history for today's closed Mutanabby deals. Resets at the start of
        each NY trading day (same convention as SB/TL, for a consistent "day"
        definition across strategies and the dashboard).
        """
        from datetime import timezone
        from src.logger import logger

        today_ny = datetime.now(NY_TZ).date().isoformat()

        if today_ny != self._daily_limit_date:
            self._daily_limit_date = today_ny
            self._daily_loss_usd = 0.0
            self._daily_trades = 0
            self._daily_limit_halted = False
            logger.info(f"[MB] Daily limits reset for {today_ny}")

        if self._daily_limit_halted:
            return False

        # deal.time is stamped in the broker's server clock, so the from/to
        # boundaries must be expressed in that same clock — mt5_cache applies
        # the measured offset and fetches the window once per loop tick for all
        # three strategies instead of once per adapter.
        try:
            deals = mt5_cache.history_deals_today(self._broker_utc_offset, NY_TZ)
        except Exception as exc:
            logger.warning(f"[MB] Failed to fetch history deals: {exc}")
            deals = []

        # Some brokers zero out `magic` on deals, so fall back to the locally
        # recorded tickets MB itself confirmed opening (src/ticket_store.py).
        own_tickets = load_tickets(strategy="MB")

        daily_pnl = 0.0
        daily_entries = 0
        for deal in deals:
            # Scope to this instance's own symbol first — with several MB
            # instances sharing MB_MAGIC, magic alone would pool every symbol's
            # deals into one count and apply one instance's cap to all.
            if deal.symbol != symbol:
                continue
            if deal.magic != MB_MAGIC and deal.position_id not in own_tickets:
                continue
            if deal.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                daily_pnl += deal.profit + deal.commission + deal.swap
                if deal.entry == mt5.DEAL_ENTRY_IN:
                    daily_entries += 1

        self._daily_loss_usd = daily_pnl
        self._daily_trades = daily_entries

        loss_limit = getattr(root_config, "MB_DAILY_LOSS_LIMIT_USD", 10.0)
        max_trades = getattr(root_config, "MB_MAX_TRADES_PER_DAY", 3)

        if daily_pnl <= -abs(loss_limit):
            logger.warning(
                f"[MB] Daily loss limit reached | PnL ${daily_pnl:.2f} <= -${loss_limit:.2f}. "
                f"No new trades today."
            )
            self._daily_limit_halted = True
            return False

        if daily_entries >= max_trades:
            logger.info(
                f"[MB] Daily trade cap reached | {daily_entries}/{max_trades} trades. "
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
            drawdown_pct = max(0.0, min(float(getattr(root_config, "MB_MAX_DRAWDOWN_PCT", 50.0)), 100.0))
            self._drawdown_floor = usable_capital * (1.0 - drawdown_pct / 100.0)
            logger.info(
                f"[MB] Drawdown floor set | Start=${usable_capital:.2f} "
                f"Floor=${self._drawdown_floor:.2f} (max {drawdown_pct:.1f}% loss)"
            )

        if usable_capital <= self._drawdown_floor:
            logger.warning(
                f"[MB] CIRCUIT BREAKER | Capital ${usable_capital:.2f} hit floor "
                f"${self._drawdown_floor:.2f}. Halting all trading and flattening."
            )
            self._drawdown_halted = True
            for ticket in list(self._open):
                self._time_exit(symbol, ticket)
            return False

        return True
