"""
Event-loop backtester for the Trendline strategy.

Mirrors silver_bullet/backtest.py's structure and fill/cost conventions
(fixed USD risk per trade, spread+slippage baked into the fill, flat
commission per round trip) so results are directly comparable, but trimmed
to Trendline's simpler rules: no session windows, market-order-only entry,
plain breakeven+trail management (no early-exit / deep-profit compression),
no time-based exit (a trade rides until stop or target).

Fill model
----------
- Signal fires on a bar's CLOSE (aggressive market-order entry, per
  trendline/strategy.py). The backtest fills at the NEXT bar's open
  (+ slippage/spread cost) to avoid same-bar lookahead while still
  reflecting "acts on this signal almost immediately".
- Within-bar stop/target priority: if both are hit in the same bar the
  stop loss wins (conservative assumption, same as Silver Bullet's).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from .config import TrendlineConfig
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
    exit_reason: Optional[str] = None   # "target" | "stop"

    # --- Context (for diagnostics) ---
    line_kind: str = ""
    touch_bar: int = 0
    pattern: str = ""

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
    """Trendline's live config carries no cost/sizing fields (position
    sizing there is derived live from MT5's own tick value/account
    balance) — these are backtest-only knobs, kept separate rather than
    bolted onto TrendlineConfig."""
    spread_points: float = 2.0
    commission_per_trade: float = 5.0
    slippage_points: float = 1.0
    risk_per_trade: float = 100.0
    point_value: float = 1.0


def run_backtest(df: pd.DataFrame, cfg: TrendlineConfig, costs: Optional[BacktestCosts] = None) -> list[Trade]:
    """
    Run the Trendline backtest over `df`.

    `df` must have columns: timestamp_ny (tz-aware), open, high, low, close,
    date_str, is_news_day (bool).
    """
    costs = costs or BacktestCosts()
    highs   = df["high"].to_numpy(dtype=float)
    lows    = df["low"].to_numpy(dtype=float)
    closes  = df["close"].to_numpy(dtype=float)
    opens   = df["open"].to_numpy(dtype=float)
    ts_ny   = df["timestamp_ny"].tolist()
    dates   = df["date_str"].tolist()
    is_news = df["is_news_day"].to_numpy(dtype=bool)

    n = len(df)
    generator = SignalGenerator(cfg)
    trades: list[Trade] = []
    trade_counter = 0

    pending: Optional[_PendingOrder] = None
    open_trade: Optional[Trade] = None

    for i in range(n):
        bar_ts    = ts_ny[i]
        bar_date  = dates[i]
        bar_open  = opens[i]
        bar_high  = highs[i]
        bar_low   = lows[i]

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

            if trade.direction == "long":
                stop_hit   = bar_low  <= trade.stop_price
                target_hit = bar_high >= trade.target_price
                if stop_hit and target_hit:
                    trade.exit_price, trade.exit_reason, closed = trade.stop_price, "stop", True
                elif stop_hit:
                    trade.exit_price, trade.exit_reason, closed = min(trade.stop_price, bar_open), "stop", True
                elif target_hit:
                    trade.exit_price = max(trade.target_price, bar_open) if bar_open > trade.target_price else trade.target_price
                    trade.exit_reason, closed = "target", True
            else:
                stop_hit   = bar_high >= trade.stop_price
                target_hit = bar_low  <= trade.target_price
                if stop_hit and target_hit:
                    trade.exit_price, trade.exit_reason, closed = trade.stop_price, "stop", True
                elif stop_hit:
                    trade.exit_price, trade.exit_reason, closed = max(trade.stop_price, bar_open), "stop", True
                elif target_hit:
                    trade.exit_price = min(trade.target_price, bar_open) if bar_open < trade.target_price else trade.target_price
                    trade.exit_reason, closed = "target", True

            if closed:
                trade.exit_time = bar_ts
                _finalise_trade(trade, costs)
                trades.append(trade)
                open_trade = None
                generator.notify_trade_closed()
            # Whether closed or not, skip a new signal check on this bar.
            continue

        # ── 2. Check pending market-order fill (next bar's open) ────────────
        if pending is not None:
            p = pending
            sig = p.signal
            cost = costs.slippage_points + costs.spread_points / 2
            fill_price = bar_open + cost if sig.direction == "long" else bar_open - cost

            # Stale-signal guard, matching live_adapter._place_market: skip
            # (don't open) if price has already moved > 0.5R from the signal.
            risk_pts_sig = abs(sig.entry_price - sig.stop_price)
            entry_slip = abs(fill_price - sig.entry_price)
            pending = None
            if risk_pts_sig <= 0 or entry_slip <= risk_pts_sig * 0.5:
                trade_counter += 1
                risk_points = abs(fill_price - sig.stop_price)
                units = costs.risk_per_trade / risk_points if risk_points > 0 else 0.0
                open_trade = Trade(
                    trade_id     = trade_counter,
                    direction    = sig.direction,
                    date         = bar_date,
                    entry_time   = bar_ts,
                    entry_price  = fill_price,
                    stop_price   = sig.stop_price,
                    target_price = sig.target_price,
                    line_kind    = sig.line_kind,
                    touch_bar    = sig.touch_bar,
                    pattern      = sig.pattern,
                    risk_points  = risk_points,
                    units        = units,
                )
                generator.notify_trade_opened()
                continue

        # ── 3. Ask strategy for a new signal ────────────────────────────────
        skip_bar = cfg.skip_news_days and bool(is_news[i])
        if pending is None and open_trade is None and not skip_bar:
            signal = generator.on_bar(
                bar_idx  = i,
                highs    = highs,
                lows     = lows,
                closes   = closes,
                opens    = opens,
                date_str = bar_date,
            )
            if signal is not None:
                pending = _PendingOrder(signal=signal, placed_bar=i, date_str=bar_date)

    if open_trade is not None:
        open_trade.exit_time   = ts_ny[-1]
        open_trade.exit_price  = closes[-1]
        open_trade.exit_reason = "time_exit"
        _finalise_trade(open_trade, costs)
        trades.append(open_trade)

    return trades


def _finalise_trade(trade: Trade, costs: BacktestCosts) -> None:
    ep, xp = trade.entry_price, trade.exit_price
    raw_points = (xp - ep) if trade.direction == "long" else (ep - xp)

    commission_points = costs.commission_per_trade / (trade.units * costs.point_value) if trade.units > 0 else 0.0
    trade.pnl_points  = raw_points - commission_points
    trade.pnl_dollars = trade.pnl_points * trade.units * costs.point_value
    trade.r_multiple  = trade.pnl_points / trade.risk_points if trade.risk_points > 0 else 0.0
