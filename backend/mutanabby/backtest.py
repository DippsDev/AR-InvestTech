"""
Event-loop backtester for the Mutanabby strategy.

Mirrors silver_bullet/backtest.py and trendline/backtest.py's structure and
fill/cost conventions (fixed USD risk per trade, spread+slippage baked into the
fill, flat commission per round trip) so results are directly comparable.

Fill model
----------
- Signal fires on a bar's CLOSE. The backtest fills at the NEXT bar's open
  (+ slippage/half-spread) to avoid same-bar look-ahead. This matters more here
  than for the other two strategies: the source indicator's own header admits
  its signals flicker during bar formation, so a same-bar fill would be
  backtesting a signal that did not exist yet.
- Within-bar stop/target priority: if both are hit in the same bar the stop
  wins (conservative, same as the other two backtesters).
- An opposite-signal exit (when enabled) fills at that bar's close rather than
  the next open, since a flip system's whole premise is acting on the flip.
  The replacement trade still waits for the next bar's open.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .config import MutanabbyConfig
from .strategy import Signal, SignalGenerator


@dataclass
class Trade:
    # --- Identity ---
    trade_id: int
    direction: str           # "long" | "short"
    date: str

    # --- Prices ---
    entry_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float

    # --- Exit ---
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None   # "target" | "target2" | "stop" | "opposite_signal" | "time_exit"

    # --- Split target (TP1/TP2) ---
    # See trendline/backtest.py's Trade for the shared semantics: one Trade row
    # per setup, `tp1_fraction` banked at TP1, remainder rides to TP2.
    target_price_2: Optional[float] = None
    tp1_fraction: float = 1.0
    tp1_hit: bool = False
    tp1_exit_price: Optional[float] = None
    tp1_exit_time: Optional[pd.Timestamp] = None

    # --- Context (for diagnostics) ---
    signal_bar: int = 0
    strength: str = ""       # chart's Buy vs Strong Buy label
    rsi_at_signal: float = float("nan")

    # --- Performance ---
    risk_points: float = 0.0
    r_multiple: Optional[float] = None
    pnl_points: Optional[float] = None
    pnl_dollars: Optional[float] = None

    # --- Position sizing ---
    units: float = 0.0

    # --- Breakeven / trailing stop tracking ---
    breakeven_triggered: bool = False
    trail_best_price: Optional[float] = None


@dataclass
class _PendingOrder:
    signal: Signal
    placed_bar: int
    date_str: str


@dataclass
class BacktestCosts:
    """Backtest-only knobs. Kept off MutanabbyConfig for the same reason
    TrendlineConfig keeps them off: live position sizing is derived from MT5's
    own tick value and account balance, not from these."""
    spread_points: float = 2.0
    commission_per_trade: float = 5.0
    slippage_points: float = 1.0
    risk_per_trade: float = 100.0
    point_value: float = 1.0
    # Abandon a pending entry if the next open gapped more than this many R
    # away from the signal price (mirrors trendline's live stale-signal guard).
    max_entry_slip_r: float = 0.5


def run_backtest(df: pd.DataFrame, cfg: MutanabbyConfig,
                 costs: Optional[BacktestCosts] = None) -> list[Trade]:
    """
    Run the Mutanabby backtest over `df`.

    `df` must have columns: timestamp_ny (tz-aware), open, high, low, close,
    date_str, is_news_day (bool).
    """
    costs = costs or BacktestCosts()
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    ts_ny = df["timestamp_ny"].tolist()
    dates = df["date_str"].tolist()
    is_news = df["is_news_day"].to_numpy(dtype=bool)

    n = len(df)
    generator = SignalGenerator(cfg, highs, lows, closes)
    bull, bear = generator.bull, generator.bear
    half_cost = costs.slippage_points + costs.spread_points / 2

    trades: list[Trade] = []
    trade_counter = 0
    pending: Optional[_PendingOrder] = None
    open_trade: Optional[Trade] = None

    for i in range(n):
        bar_ts = ts_ny[i]
        bar_date = dates[i]
        bar_open = opens[i]
        bar_high = highs[i]
        bar_low = lows[i]
        bar_close = closes[i]

        # ── 1. Manage open trade ────────────────────────────────────────────
        if open_trade is not None:
            trade = open_trade
            closed = False

            if cfg.breakeven_r > 0 and not trade.breakeven_triggered:
                trigger_dist = trade.risk_points * cfg.breakeven_r
                if trade.direction == "long":
                    if bar_high >= trade.entry_price + trigger_dist:
                        trade.stop_price = trade.entry_price
                        trade.breakeven_triggered = True
                else:
                    if bar_low <= trade.entry_price - trigger_dist:
                        trade.stop_price = trade.entry_price
                        trade.breakeven_triggered = True

            if cfg.trail_r > 0 and trade.breakeven_triggered:
                if trade.direction == "long":
                    if trade.trail_best_price is None or bar_high > trade.trail_best_price:
                        trade.trail_best_price = bar_high
                    new_trail_stop = trade.trail_best_price - cfg.trail_r * trade.risk_points
                    if new_trail_stop > trade.stop_price:
                        trade.stop_price = new_trail_stop
                else:
                    if trade.trail_best_price is None or bar_low < trade.trail_best_price:
                        trade.trail_best_price = bar_low
                    new_trail_stop = trade.trail_best_price + cfg.trail_r * trade.risk_points
                    if new_trail_stop < trade.stop_price:
                        trade.stop_price = new_trail_stop

            # TP1 until it fills, TP2 afterwards. Unsplit, this is always TP1
            # and the branch below closes the whole position as it always did.
            splitting = trade.target_price_2 is not None
            active_target = (
                trade.target_price_2 if (splitting and trade.tp1_hit) else trade.target_price
            )

            if trade.direction == "long":
                stop_hit = bar_low <= trade.stop_price
                target_hit = bar_high >= active_target
                if stop_hit and target_hit:
                    trade.exit_price, trade.exit_reason, closed = trade.stop_price, "stop", True
                elif stop_hit:
                    trade.exit_price, trade.exit_reason, closed = min(trade.stop_price, bar_open), "stop", True
                elif target_hit:
                    fill = max(active_target, bar_open) if bar_open > active_target else active_target
                    if splitting and not trade.tp1_hit:
                        trade.tp1_hit, trade.tp1_exit_price, trade.tp1_exit_time = True, fill, bar_ts
                        if bar_high >= trade.target_price_2:
                            tp2 = trade.target_price_2
                            trade.exit_price = max(tp2, bar_open) if bar_open > tp2 else tp2
                            trade.exit_reason, closed = "target2", True
                    else:
                        trade.exit_price = fill
                        trade.exit_reason, closed = ("target2" if splitting else "target"), True
            else:
                stop_hit = bar_high >= trade.stop_price
                target_hit = bar_low <= active_target
                if stop_hit and target_hit:
                    trade.exit_price, trade.exit_reason, closed = trade.stop_price, "stop", True
                elif stop_hit:
                    trade.exit_price, trade.exit_reason, closed = max(trade.stop_price, bar_open), "stop", True
                elif target_hit:
                    fill = min(active_target, bar_open) if bar_open < active_target else active_target
                    if splitting and not trade.tp1_hit:
                        trade.tp1_hit, trade.tp1_exit_price, trade.tp1_exit_time = True, fill, bar_ts
                        if bar_low <= trade.target_price_2:
                            tp2 = trade.target_price_2
                            trade.exit_price = min(tp2, bar_open) if bar_open < tp2 else tp2
                            trade.exit_reason, closed = "target2", True
                    else:
                        trade.exit_price = fill
                        trade.exit_reason, closed = ("target2" if splitting else "target"), True

            # Flip exit: only if the bar didn't already stop out or hit target.
            flip_exit = False
            if not closed and cfg.exit_on_opposite_signal:
                opposite = bear[i] if trade.direction == "long" else bull[i]
                if opposite:
                    trade.exit_price = bar_close - half_cost if trade.direction == "long" else bar_close + half_cost
                    trade.exit_reason, closed, flip_exit = "opposite_signal", True, True

            if closed:
                trade.exit_time = bar_ts
                _finalise_trade(trade, costs)
                trades.append(trade)
                open_trade = None
                generator.notify_trade_closed()

            # A stop/target exit ends the bar. A flip exit falls through so the
            # very signal that closed the trade can open the reverse one.
            if not flip_exit:
                continue

        # ── 2. Check pending market-order fill (next bar's open) ────────────
        if pending is not None:
            sig = pending.signal
            fill_price = bar_open + half_cost if sig.direction == "long" else bar_open - half_cost

            risk_pts_sig = abs(sig.entry_price - sig.stop_price)
            entry_slip = abs(fill_price - sig.entry_price)
            pending = None
            if risk_pts_sig <= 0 or entry_slip <= risk_pts_sig * costs.max_entry_slip_r:
                trade_counter += 1
                risk_points = abs(fill_price - sig.stop_price)
                units = costs.risk_per_trade / risk_points if risk_points > 0 else 0.0
                open_trade = Trade(
                    trade_id      = trade_counter,
                    direction     = sig.direction,
                    date          = bar_date,
                    entry_time    = bar_ts,
                    entry_price   = fill_price,
                    stop_price    = sig.stop_price,
                    target_price  = sig.target_price,
                    target_price_2 = sig.target_price_2,
                    tp1_fraction  = cfg.tp1_fraction if sig.target_price_2 is not None else 1.0,
                    signal_bar    = sig.bar_idx,
                    strength      = sig.strength,
                    rsi_at_signal = sig.rsi,
                    risk_points   = risk_points,
                    units         = units,
                )
                generator.notify_trade_opened()
                continue

        # ── 3. Ask strategy for a new signal ────────────────────────────────
        skip_bar = cfg.skip_news_days and bool(is_news[i])
        if pending is None and open_trade is None and not skip_bar:
            signal = generator.on_bar(bar_idx=i, date_str=bar_date)
            if signal is not None:
                pending = _PendingOrder(signal=signal, placed_bar=i, date_str=bar_date)

    if open_trade is not None:
        open_trade.exit_time = ts_ny[-1]
        open_trade.exit_price = closes[-1]
        open_trade.exit_reason = "time_exit"
        _finalise_trade(open_trade, costs)
        trades.append(open_trade)

    return trades


def _finalise_trade(trade: Trade, costs: BacktestCosts) -> None:
    """Book P/L, size-weighting the two legs when TP1 filled.

    Same convention as trendline/backtest.py: `pnl_points` is the size-weighted
    per-unit figure (so `r_multiple` stays comparable with unsplit trades) while
    `pnl_dollars` is the total across the whole original position, and the flat
    commission is charged once per leg that opened.
    """
    ep = trade.entry_price
    sign = 1.0 if trade.direction == "long" else -1.0

    legs: list[tuple[float, float]] = []   # (fraction, exit_price)
    if trade.tp1_hit and trade.tp1_exit_price is not None:
        legs.append((trade.tp1_fraction, trade.tp1_exit_price))
        legs.append((1.0 - trade.tp1_fraction, trade.exit_price))
    else:
        legs.append((1.0, trade.exit_price))

    per_unit_commission = (
        costs.commission_per_trade / (trade.units * costs.point_value)
        if trade.units > 0 else 0.0
    )

    pnl_points = 0.0
    for fraction, exit_price in legs:
        if fraction <= 0:
            continue
        gross = sign * (exit_price - ep)
        pnl_points += fraction * (gross - per_unit_commission / fraction)

    trade.pnl_points = pnl_points
    trade.pnl_dollars = pnl_points * trade.units * costs.point_value
    trade.r_multiple = pnl_points / trade.risk_points if trade.risk_points > 0 else 0.0
