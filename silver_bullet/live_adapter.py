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
- Cycle 1 is an initialisation pass: all historical bars feed the signal generator to
  build up session state, but no orders are placed.  Orders only fire from cycle 2
  onward, so we never act on a signal that fired 30-40 minutes before the bot started.
- Magic number 202406122 is distinct from the scalping bot (202406121).
"""
from __future__ import annotations

from datetime import datetime, time as dtime
from typing import Optional
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import pandas as pd

from .config import SilverBulletConfig
from .strategy import Signal, SignalGenerator

NY_TZ = ZoneInfo("America/New_York")
SB_MAGIC = 202406122


class SilverBulletLiveAdapter:
    """Stateful, bar-by-bar adapter.  Instantiate once; call .cycle() every 30 s."""

    def __init__(self, cfg: SilverBulletConfig):
        self._cfg = cfg
        self._generator = SignalGenerator(cfg)
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cycle(self, symbol: str) -> None:
        """Called from the main bot loop.  Manages the full lifecycle of one SB setup."""
        from src.logger import logger

        bars = self._fetch_bars(symbol, n=150)
        if bars is None or len(bars) < 10:
            logger.warning(f"[SB] Bar fetch failed for {symbol}")
            return

        # Drop the currently-forming (incomplete) bar
        completed = bars.iloc[:-1]
        if completed.empty:
            return

        times  = completed.index.tolist()          # list of tz-aware UTC pd.Timestamps
        highs  = completed["high"].to_numpy(dtype=float)
        lows   = completed["low"].to_numpy(dtype=float)
        closes = completed["close"].to_numpy(dtype=float)
        opens  = completed["open"].to_numpy(dtype=float)

        # 1. Check if pending order was filled by MT5
        self._sync_fill_status(symbol)

        # 2. Determine session context
        last_ny = times[-1].astimezone(NY_TZ)
        in_window, _ = self._window_at(last_ny)
        past_cutoff  = self._is_cutoff(last_ny)
        in_off_hours = self._cfg.off_hours_trading and not in_window and not past_cutoff

        # Reset daily off-hours fill counter at day change
        today_ny = datetime.now(NY_TZ).date().isoformat()
        if today_ny != self._off_hours_date:
            self._off_hours_date  = today_ny
            self._off_hours_fills = 0

        # 3. Manage open position
        if self._open_ticket is not None:
            self._sync_position(symbol)
            if self._open_ticket is not None:
                self._check_breakeven(symbol)
            if self._open_ticket is not None:
                # Regular-window trade: close when window ends.
                # Off-hours trade: close at daily cutoff.
                should_exit = (
                    (not self._open_is_off_hours and not in_window) or
                    (self._open_is_off_hours and past_cutoff)
                )
                if should_exit:
                    self._time_exit(symbol)
            return

        # 4. Manage pending order
        if self._pending_ticket is not None:
            should_cancel = (
                (not self._pending_is_off_hours and not in_window) or
                (self._pending_is_off_hours and past_cutoff)
            )
            if should_cancel:
                self._cancel_pending()
            return

        # 5. Feed unprocessed bars through the signal generator
        for i, ts in enumerate(times):
            if self._last_bar_time is not None and ts <= self._last_bar_time:
                continue

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

            # Act only after initialisation and only on today's signals
            if signal is not None and self._initialized and date_str == today_ny:
                if bar_off_hrs and self._off_hours_fills >= self._cfg.off_hours_max_trades:
                    logger.info(
                        f"[SB] Off-hours cap ({self._cfg.off_hours_max_trades}) reached — skipping"
                    )
                    continue
                lots = self._compute_lots(symbol, signal)
                if lots is not None:
                    self._place_limit(symbol, signal, lots)
                    self._open_signal          = signal
                    self._pending_is_off_hours = bar_off_hrs
                break  # one pending order per cycle
            elif signal is not None:
                logger.info(
                    f"[SB] Signal skipped | init={self._initialized} | "
                    f"date={date_str} today={today_ny}"
                )

        # Advance the watermark
        if times:
            self._last_bar_time = times[-1]

        self._initialized = True

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

        sig      = self._open_signal
        fill     = self._open_fill_price
        risk_pts = abs(fill - sig.stop_price)
        is_long  = sig.direction == "long"
        current_px = tick.bid if is_long else tick.ask

        # Phase 1 — breakeven
        if not self._breakeven_triggered and self._cfg.breakeven_r > 0:
            trigger_dist = risk_pts * self._cfg.breakeven_r
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
        if self._breakeven_triggered and self._cfg.trail_r > 0:
            if is_long:
                if self._trail_best_price is None or current_px > self._trail_best_price:
                    self._trail_best_price = current_px
                new_sl = self._trail_best_price - risk_pts * self._cfg.trail_r
            else:
                if self._trail_best_price is None or current_px < self._trail_best_price:
                    self._trail_best_price = current_px
                new_sl = self._trail_best_price + risk_pts * self._cfg.trail_r

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

    def _window_at(self, ts_ny: datetime) -> tuple[bool, Optional[int]]:
        t = ts_ny.time()
        for wid, (start_s, end_s) in enumerate(self._cfg.windows):
            sh, sm = map(int, start_s.split(":"))
            eh, em = map(int, end_s.split(":"))
            if dtime(sh, sm) <= t < dtime(eh, em):
                return True, wid
        return False, None

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

        risk_usd  = account.balance * 0.01   # 1% risk per trade
        risk_pts  = abs(signal.entry_price - signal.stop_price)
        tick_val  = sym_info.trade_tick_value
        tick_size = sym_info.trade_tick_size

        if risk_pts <= 0 or tick_val <= 0 or tick_size <= 0:
            return sym_info.volume_min

        value_per_pt = tick_val / tick_size
        raw  = risk_usd / (risk_pts * value_per_pt)
        step = sym_info.volume_step
        lots = round(raw / step) * step
        lots = max(sym_info.volume_min, min(lots, sym_info.volume_max, 1.0))
        return round(lots, 2)
