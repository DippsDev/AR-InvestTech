"""
Event-loop backtester.

Processes bars in strict chronological order.  For each bar:
  1. Manage any open position (check stop / target hit within bar's range).
  2. Check if a pending limit order was filled.
  3. Ask SignalGenerator for a new signal if no position/order is active.

Fill model
----------
- Long limit at P : fills when bar_low  <= P.  Fill price = P (+ slippage/spread).
                    If bar opens below P (gap), fills at open.
- Short limit at P: fills when bar_high >= P.  Fill price = P (- slippage/spread).
                    If bar opens above P (gap), fills at open.
- Within-bar stop/target priority: if both stop and target are hit in the same bar
  the stop loss wins (conservative assumption).
- Session-end time exit: trade open when window closes → exited at NEXT bar's open.
"""
from __future__ import annotations

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from silver_bullet.run_backtest import main
    sys.exit(main())

import math
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import time as dtime
from typing import Optional

import numpy as np
import pandas as pd

from .config import SilverBulletConfig
from .strategy import Signal, SignalGenerator


# ---------------------------------------------------------------------------
# Trade record
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    # --- Identity ---
    trade_id: int
    direction: str           # "long" | "short"
    date: str
    window_id: int

    # --- Prices ---
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float

    # --- Exit ---
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None   # "target" | "stop" | "time_exit"

    # --- Context (for diagnostics) ---
    sweep_level: float = 0.0
    sweep_bar: int = 0
    fvg_zone: tuple = field(default_factory=tuple)
    fvg_bar: int = 0

    # --- Performance ---
    risk_points: float = 0.0
    r_multiple: Optional[float] = None
    pnl_points: Optional[float] = None
    pnl_dollars: Optional[float] = None

    # --- Position sizing ---
    units: float = 0.0    # contracts/units derived from risk_per_trade

    # --- Breakeven / trailing stop tracking ---
    breakeven_triggered: bool = False
    trail_best_price: Optional[float] = None
    is_news_trade: bool = False   # True when opened on a high-impact news day
    is_off_hours: bool = False    # True when opened in an off-hours scalp window


# ---------------------------------------------------------------------------
# Internal pending order
# ---------------------------------------------------------------------------

@dataclass
class _PendingOrder:
    signal: Signal
    placed_bar: int
    date_str: str
    is_off_hours: bool = False


# ---------------------------------------------------------------------------
# Main backtester
# ---------------------------------------------------------------------------

def run_backtest(df: pd.DataFrame, cfg: SilverBulletConfig) -> list[Trade]:
    """
    Run the Silver Bullet backtest over `df`.

    `df` must have columns:
      timestamp_ny (tz-aware), open, high, low, close, in_window (bool),
      window_id (nullable int).

    Returns a list of completed Trade records.
    """
    highs        = df["high"].to_numpy(dtype=float)
    lows         = df["low"].to_numpy(dtype=float)
    closes       = df["close"].to_numpy(dtype=float)
    opens        = df["open"].to_numpy(dtype=float)
    # Use a Python list so each element is a tz-aware pd.Timestamp (NY local)
    ts_ny        = df["timestamp_ny"].tolist()
    in_win       = df["in_window"].to_numpy(dtype=bool)
    win_ids      = df["window_id"].to_numpy()        # can be pd.NA
    prev_day_biases = df["prev_day_bias"].to_numpy(dtype=int)  if "prev_day_bias" in df.columns else None
    is_news_day     = df["is_news_day"].to_numpy(dtype=bool) if "is_news_day"  in df.columns else None

    n = len(df)
    generator = SignalGenerator(cfg)
    trades: list[Trade] = []
    trade_counter = 0

    pending: Optional[_PendingOrder] = None
    open_trade: Optional[Trade] = None

    for i in range(n):
        bar_ts     = ts_ny[i]          # tz-aware NY-local pd.Timestamp
        bar_date   = bar_ts.date().isoformat()
        bar_wid    = int(win_ids[i]) if not pd.isna(win_ids[i]) else None
        bar_open   = opens[i]
        bar_high   = highs[i]
        bar_low    = lows[i]
        bar_close  = closes[i]
        bar_in_win = bool(in_win[i])

        # Off-hours scalp bars are outside the configured windows but before
        # the daily off-hours cutoff. Each clock-hour gets its own window ID.
        bar_off_hrs = (
            cfg.off_hours_trading
            and not bar_in_win
            and not _is_past_cutoff(bar_ts.time(), cfg.off_hours_close_time)
        )
        bar_in_entry = bar_in_win or bar_off_hrs
        entry_wid    = bar_wid if bar_in_win else (100 + bar_ts.hour if bar_off_hrs else None)

        # ── 1. Manage open trade ────────────────────────────────────────────
        if open_trade is not None:
            trade = open_trade
            closed = False

            # Off-hours trades use their own tighter scalp parameters.
            eff_cfg = _off_hours_cfg(cfg) if trade.is_off_hours else cfg

            # Time-exit rules differ: regular trades exit when the window closes;
            # off-hours trades exit at the off-hours cutoff or on a new day.
            if trade.is_off_hours:
                time_exit = (
                    _is_past_cutoff(bar_ts.time(), cfg.off_hours_close_time)
                    or bar_date != trade.date
                )
            else:
                time_exit = not bar_in_win

            # ── Breakeven: slide stop to entry once price reaches +N×R ────
            if eff_cfg.breakeven_r > 0 and not trade.breakeven_triggered:
                trigger_dist = trade.risk_points * eff_cfg.breakeven_r
                if trade.direction == "long":
                    if bar_high >= trade.entry_price + trigger_dist:
                        trade.stop_price = trade.entry_price
                        trade.breakeven_triggered = True
                else:
                    if bar_low <= trade.entry_price - trigger_dist:
                        trade.stop_price = trade.entry_price
                        trade.breakeven_triggered = True

            # ── Trailing stop: follow price at trail_r distance after breakeven ──
            # Skip trail on news-day trades so the extended 5R target has room.
            trail_active = eff_cfg.trail_r > 0 and not (trade.is_news_trade and cfg.news_disable_trail)
            if trail_active and trade.breakeven_triggered:
                if trade.direction == "long":
                    if trade.trail_best_price is None or bar_high > trade.trail_best_price:
                        trade.trail_best_price = bar_high
                    best_r = (trade.trail_best_price - trade.entry_price) / trade.risk_points if trade.risk_points > 0 else 0.0
                    active_trail_r = (eff_cfg.deep_trail_r
                                      if eff_cfg.deep_profit_r > 0 and best_r >= eff_cfg.deep_profit_r
                                      else eff_cfg.trail_r)
                    new_trail_stop = trade.trail_best_price - active_trail_r * trade.risk_points
                    if new_trail_stop > trade.stop_price:
                        trade.stop_price = new_trail_stop
                else:
                    if trade.trail_best_price is None or bar_low < trade.trail_best_price:
                        trade.trail_best_price = bar_low
                    best_r = (trade.entry_price - trade.trail_best_price) / trade.risk_points if trade.risk_points > 0 else 0.0
                    active_trail_r = (eff_cfg.deep_trail_r
                                      if eff_cfg.deep_profit_r > 0 and best_r >= eff_cfg.deep_profit_r
                                      else eff_cfg.trail_r)
                    new_trail_stop = trade.trail_best_price + active_trail_r * trade.risk_points
                    if new_trail_stop < trade.stop_price:
                        trade.stop_price = new_trail_stop

            # ── Early exit: cut partial loss before structural stop is reached ──
            # Only applies when breakeven has not yet triggered — once we're
            # protecting at entry the normal stop/trail handles everything.
            if not closed and eff_cfg.early_exit_r > 0 and not trade.breakeven_triggered:
                if trade.direction == "long":
                    early_level = trade.entry_price - eff_cfg.early_exit_r * trade.risk_points
                    if bar_low <= early_level and early_level > trade.stop_price:
                        trade.exit_price = min(early_level, bar_open)
                        trade.exit_reason = "stop"
                        closed = True
                else:
                    early_level = trade.entry_price + eff_cfg.early_exit_r * trade.risk_points
                    if bar_high >= early_level and early_level < trade.stop_price:
                        trade.exit_price = max(early_level, bar_open)
                        trade.exit_reason = "stop"
                        closed = True

            if trade.direction == "long":
                stop_hit   = bar_low  <= trade.stop_price
                target_hit = bar_high >= trade.target_price

                if stop_hit and target_hit:
                    # Ambiguous — conservative: stop wins
                    trade.exit_price  = trade.stop_price
                    trade.exit_reason = "stop"
                    closed = True
                elif stop_hit:
                    trade.exit_price  = min(trade.stop_price, bar_open)  # gap-down
                    trade.exit_reason = "stop"
                    closed = True
                elif target_hit:
                    trade.exit_price  = max(trade.target_price, bar_open) if bar_open > trade.target_price else trade.target_price
                    trade.exit_reason = "target"
                    closed = True
                elif time_exit:
                    # Window closed — time exit at this bar's open (next bar relative to placement)
                    trade.exit_price  = bar_open
                    trade.exit_reason = "time_exit"
                    closed = True

            else:  # short
                stop_hit   = bar_high >= trade.stop_price
                target_hit = bar_low  <= trade.target_price

                if stop_hit and target_hit:
                    trade.exit_price  = trade.stop_price
                    trade.exit_reason = "stop"
                    closed = True
                elif stop_hit:
                    trade.exit_price  = max(trade.stop_price, bar_open)  # gap-up
                    trade.exit_reason = "stop"
                    closed = True
                elif target_hit:
                    trade.exit_price  = min(trade.target_price, bar_open) if bar_open < trade.target_price else trade.target_price
                    trade.exit_reason = "target"
                    closed = True
                elif time_exit:
                    trade.exit_price  = bar_open
                    trade.exit_reason = "time_exit"
                    closed = True

            if closed:
                trade.exit_time = bar_ts
                _finalise_trade(trade, cfg)
                trades.append(trade)
                open_trade = None
            # Whether closed or not — continue processing this bar for no new entry
            if open_trade is None:
                # Trade just closed — still skip new entry this bar for safety
                continue

        # ── 2. Check pending limit fill ─────────────────────────────────────
        if pending is not None:
            p = pending
            sig = p.signal

            # Cancel if window changed, session ended, or day rolled over.
            if p.is_off_hours:
                cancelled = (
                    bar_date != p.date_str
                    or _is_past_cutoff(bar_ts.time(), cfg.off_hours_close_time)
                    or not bar_in_entry
                    or entry_wid != sig.window_id
                )
            else:
                cancelled = (
                    bar_date != p.date_str
                    or not bar_in_win
                    or bar_wid != sig.window_id
                )
            if cancelled:
                pending = None
            else:
                fill_price = _check_fill(sig, bar_open, bar_high, bar_low, cfg)
                if fill_price is not None:
                    trade_counter += 1
                    risk_points = abs(fill_price - sig.stop_price)
                    units = cfg.risk_per_trade / risk_points if risk_points > 0 else 0.0

                    fill_is_news = is_news_day is not None and bool(is_news_day[i])
                    open_trade = Trade(
                        trade_id      = trade_counter,
                        direction     = sig.direction,
                        date          = bar_date,
                        window_id     = sig.window_id,
                        entry_time    = bar_ts,
                        entry_price   = fill_price,
                        stop_price    = sig.stop_price,
                        target_price  = sig.target_price,
                        sweep_level   = sig.sweep_level,
                        sweep_bar     = sig.sweep_bar,
                        fvg_zone      = sig.fvg_zone,
                        fvg_bar       = sig.fvg_bar,
                        risk_points   = risk_points,
                        units         = units,
                        is_news_trade = fill_is_news,
                        is_off_hours  = p.is_off_hours,
                    )
                    pending = None
                    continue

        # ── 3. Ask strategy for a new signal ────────────────────────────────
        on_news_day = is_news_day is not None and bool(is_news_day[i])
        skip_bar    = cfg.skip_news_days and on_news_day
        if bar_in_entry and pending is None and open_trade is None and entry_wid is not None and not skip_bar:
            p_bias = int(prev_day_biases[i]) if prev_day_biases is not None else 0

            # Off-hours setups use their own tighter scalp parameters.
            gen_cfg = _off_hours_cfg(cfg) if bar_off_hrs else cfg
            old_cfg = generator._cfg
            generator._cfg = gen_cfg
            try:
                signal = generator.on_bar(
                    bar_idx       = i,
                    highs         = highs,
                    lows          = lows,
                    closes        = closes,
                    opens         = opens,
                    in_window     = bar_in_entry,
                    window_id     = entry_wid,
                    date_str      = bar_date,
                    prev_day_bias = p_bias,
                )
            finally:
                generator._cfg = old_cfg

            # On high-impact news days extend the profit target to capture the larger move
            if signal is not None and on_news_day and cfg.news_rr > 0:
                risk = abs(signal.entry_price - signal.stop_price)
                signal.target_price = (
                    signal.entry_price + cfg.news_rr * risk if signal.direction == "long"
                    else signal.entry_price - cfg.news_rr * risk
                )
            if signal is not None:
                pending = _PendingOrder(
                    signal       = signal,
                    placed_bar   = i,
                    date_str     = bar_date,
                    is_off_hours = bar_off_hrs,
                )

    # Flush any trade still open at end of data
    if open_trade is not None:
        open_trade.exit_time   = ts_ny[-1]
        open_trade.exit_price  = closes[-1]
        open_trade.exit_reason = "time_exit"
        _finalise_trade(open_trade, cfg)
        trades.append(open_trade)

    return trades


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_fill(
    sig: Signal,
    bar_open: float,
    bar_high: float,
    bar_low: float,
    cfg: SilverBulletConfig,
) -> Optional[float]:
    """Return the actual fill price if the limit order is hit, else None.

    Fill model: always fill at the stated limit price ± slippage/spread cost.
    Gap-opens are treated as immediately filling at the limit (conservative —
    in reality you'd do better on gap-ups for shorts and gap-downs for longs,
    but adjusting the fill would require recalculating stop/target levels and
    complicates the model without improving accuracy on real tick data).
    """
    cost = cfg.slippage_points + cfg.spread_points / 2

    if sig.direction == "long":
        if bar_low <= sig.entry_price:
            return sig.entry_price + cost          # buy limit: pay a bit more
    else:
        if bar_high >= sig.entry_price:
            return sig.entry_price - cost          # sell limit: receive a bit less

    return None


def _is_past_cutoff(t: dtime, close_time_str: str) -> bool:
    """Return True if time-of-day is at/past the configured off-hours close."""
    h, m = map(int, close_time_str.split(":"))
    return t >= dtime(h, m)


def _off_hours_cfg(cfg: SilverBulletConfig) -> SilverBulletConfig:
    """Return a config copy with the tighter off-hours scalp overrides."""
    return _dc_replace(
        cfg,
        fvg_min_points  = cfg.off_hours_fvg_min_points,
        min_risk_points = cfg.off_hours_min_risk_points,
        target_mode     = cfg.off_hours_target_mode,
        rr              = cfg.off_hours_rr,
        breakeven_r     = cfg.off_hours_breakeven_r,
        trail_r         = cfg.off_hours_trail_r,
        early_exit_r    = cfg.off_hours_early_exit_r,
        deep_profit_r   = cfg.off_hours_deep_profit_r,
        deep_trail_r    = cfg.off_hours_deep_trail_r,
    )


def _finalise_trade(trade: Trade, cfg: SilverBulletConfig) -> None:
    """Compute pnl_points, r_multiple, pnl_dollars in-place."""
    ep = trade.entry_price
    xp = trade.exit_price

    if trade.direction == "long":
        raw_points = xp - ep
    else:
        raw_points = ep - xp

    # Commission is per round-trip
    commission_points = cfg.commission_per_trade / (trade.units * cfg.point_value) if trade.units > 0 else 0.0
    trade.pnl_points  = raw_points - commission_points
    trade.pnl_dollars = trade.pnl_points * trade.units * cfg.point_value

    if trade.risk_points > 0:
        trade.r_multiple = trade.pnl_points / trade.risk_points
    else:
        trade.r_multiple = 0.0
