"""Aggregate performance statistics from a list of Trade records."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from dataclasses import asdict
from typing import List, Optional

import pandas as pd

from .backtest import Trade


def compute_metrics(trades: List[Trade]) -> dict:
    """Return a summary dict for the full trade list."""
    if not trades:
        return _empty_metrics()

    pnls     = [t.pnl_dollars for t in trades if t.pnl_dollars is not None]
    rs       = [t.r_multiple  for t in trades if t.r_multiple  is not None]
    wins     = [p for p in pnls if p > 0]
    losses   = [p for p in pnls if p <= 0]
    n        = len(trades)

    # --- P/L ---
    net_pnl       = sum(pnls)
    gross_profit  = sum(wins)
    gross_loss    = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf

    # --- Win rate / R ---
    win_rate      = len(wins) / n if n > 0 else 0.0
    avg_r         = sum(rs) / len(rs) if rs else 0.0
    expectancy    = net_pnl / n if n > 0 else 0.0

    # --- Max drawdown on cumulative P/L curve ---
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cum += p
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    # --- Trades per day ---
    if trades:
        dates = sorted({t.date for t in trades})
        num_days   = len(dates)
        trades_day = n / num_days if num_days > 0 else 0.0
    else:
        trades_day = 0.0

    exit_counts = {}
    for t in trades:
        exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1

    return {
        "num_trades"        : n,
        "net_pnl_usd"       : round(net_pnl, 2),
        "win_rate_pct"      : round(win_rate * 100, 1),
        "avg_r"             : round(avg_r, 3),
        "expectancy_usd"    : round(expectancy, 2),
        "profit_factor"     : round(profit_factor, 2) if profit_factor != math.inf else "inf",
        "max_drawdown_usd"  : round(max_dd, 2),
        "gross_profit_usd"  : round(gross_profit, 2),
        "gross_loss_usd"    : round(gross_loss, 2),
        "trades_per_day"    : round(trades_day, 2),
        "exit_breakdown"    : exit_counts,
    }


def _empty_metrics() -> dict:
    return {
        "num_trades"        : 0,
        "net_pnl_usd"       : 0.0,
        "win_rate_pct"      : 0.0,
        "avg_r"             : 0.0,
        "expectancy_usd"    : 0.0,
        "profit_factor"     : 0.0,
        "max_drawdown_usd"  : 0.0,
        "gross_profit_usd"  : 0.0,
        "gross_loss_usd"    : 0.0,
        "trades_per_day"    : 0.0,
        "exit_breakdown"    : {},
    }


def print_metrics(metrics: dict) -> None:
    """Pretty-print the metrics dict."""
    print("\n" + "=" * 50)
    print("  SILVER BULLET BACKTEST RESULTS")
    print("=" * 50)
    print(f"  Trades          : {metrics['num_trades']}")
    print(f"  Trades / day    : {metrics['trades_per_day']}")
    print(f"  Win rate        : {metrics['win_rate_pct']}%")
    print(f"  Average R       : {metrics['avg_r']}")
    print(f"  Expectancy      : ${metrics['expectancy_usd']}")
    print(f"  Net P/L         : ${metrics['net_pnl_usd']}")
    print(f"  Gross profit    : ${metrics['gross_profit_usd']}")
    print(f"  Gross loss      : ${metrics['gross_loss_usd']}")
    print(f"  Profit factor   : {metrics['profit_factor']}")
    print(f"  Max drawdown    : ${metrics['max_drawdown_usd']}")
    exits = metrics['exit_breakdown']
    print(f"  Exit breakdown  : target={exits.get('target',0)}  "
          f"stop={exits.get('stop',0)}  "
          f"time={exits.get('time_exit',0)}")
    print("=" * 50 + "\n")


def trade_log_df(trades: List[Trade]) -> pd.DataFrame:
    """Return a DataFrame suitable for CSV export or display."""
    rows = []
    for t in trades:
        rows.append({
            "trade_id"    : t.trade_id,
            "date"        : t.date,
            "window_id"   : t.window_id,
            "direction"   : t.direction,
            "entry_time"  : t.entry_time,
            "entry_price" : t.entry_price,
            "stop_price"  : t.stop_price,
            "target_price": t.target_price,
            "exit_time"   : t.exit_time,
            "exit_price"  : t.exit_price,
            "exit_reason" : t.exit_reason,
            "r_multiple"  : round(t.r_multiple, 3) if t.r_multiple is not None else None,
            "pnl_points"  : round(t.pnl_points, 2) if t.pnl_points is not None else None,
            "pnl_usd"     : round(t.pnl_dollars, 2) if t.pnl_dollars is not None else None,
            "sweep_level"         : t.sweep_level,
            "fvg_bottom"          : t.fvg_zone[0] if t.fvg_zone else None,
            "fvg_top"             : t.fvg_zone[1] if t.fvg_zone else None,
            "units"               : round(t.units, 4),
            "breakeven_triggered" : t.breakeven_triggered,
        })
    return pd.DataFrame(rows)


def save_results_json(
    trades: List[Trade],
    metrics: dict,
    cfg,
    output_path: str,
    data_file: Optional[str] = None,
    df=None,
) -> None:
    """Save full backtest results (meta, config, metrics, equity curve, trades) to JSON."""

    def _ts(v) -> Optional[str]:
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        return str(v)

    def _safe(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        if isinstance(v, float) and math.isinf(v):
            return None
        return v

    # ── Meta ──────────────────────────────────────────────────────────────────
    meta: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_file": data_file,
    }
    if df is not None:
        meta["date_range"] = {
            "start": str(df["timestamp_ny"].iloc[0].date()),
            "end":   str(df["timestamp_ny"].iloc[-1].date()),
        }
        meta["total_bars"]  = int(len(df))
        meta["window_bars"] = int(df["in_window"].sum())

    # ── Config ─────────────────────────────────────────────────────────────────
    cfg_dict = {
        "symbol":               cfg.symbol,
        "timeframe_minutes":    cfg.timeframe_minutes,
        "windows":              [list(w) for w in cfg.windows],
        "swing_lookback":       cfg.swing_lookback,
        "sweep_lookback":       cfg.sweep_lookback,
        "fvg_min_points":       cfg.fvg_min_points,
        "entry_in_fvg":         cfg.entry_in_fvg,
        "stop_buffer_points":   cfg.stop_buffer_points,
        "target_mode":          cfg.target_mode,
        "rr":                   cfg.rr,
        "one_trade_per_window": cfg.one_trade_per_window,
        "min_risk_points":      cfg.min_risk_points,
        "spread_points":        cfg.spread_points,
        "commission_per_trade": cfg.commission_per_trade,
        "slippage_points":      cfg.slippage_points,
        "risk_per_trade":       cfg.risk_per_trade,
        "point_value":          cfg.point_value,
    }

    # ── Metrics (make JSON-safe) ────────────────────────────────────────────────
    metrics_clean = {k: _safe(v) for k, v in metrics.items()}

    # ── Equity curve ──────────────────────────────────────────────────────────
    equity_curve = []
    cumulative = 0.0
    for t in trades:
        pnl = _safe(t.pnl_dollars) or 0.0
        cumulative = round(cumulative + pnl, 2)
        equity_curve.append({
            "trade_id":           t.trade_id,
            "date":               t.date,
            "exit_time":          _ts(t.exit_time),
            "pnl_usd":            _safe(round(pnl, 2)),
            "cumulative_pnl_usd": cumulative,
        })

    # ── Trade list ────────────────────────────────────────────────────────────
    trade_list = []
    for t in trades:
        trade_list.append({
            "trade_id":    t.trade_id,
            "date":        t.date,
            "window_id":   t.window_id,
            "direction":   t.direction,
            "entry_time":  _ts(t.entry_time),
            "entry_price": _safe(t.entry_price),
            "stop_price":  _safe(t.stop_price),
            "target_price":_safe(t.target_price),
            "exit_time":   _ts(t.exit_time),
            "exit_price":  _safe(t.exit_price),
            "exit_reason": t.exit_reason,
            "risk_points": _safe(round(t.risk_points, 2)),
            "r_multiple":  _safe(round(t.r_multiple, 3)) if t.r_multiple is not None else None,
            "pnl_points":  _safe(round(t.pnl_points, 2)) if t.pnl_points is not None else None,
            "pnl_usd":     _safe(round(t.pnl_dollars, 2)) if t.pnl_dollars is not None else None,
            "units":       _safe(round(t.units, 4)),
            "sweep_level":         _safe(t.sweep_level),
            "fvg_bottom":          _safe(t.fvg_zone[0]) if t.fvg_zone else None,
            "fvg_top":             _safe(t.fvg_zone[1]) if t.fvg_zone else None,
            "breakeven_triggered": t.breakeven_triggered,
        })

    payload = {
        "meta":         meta,
        "config":       cfg_dict,
        "metrics":      metrics_clean,
        "equity_curve": equity_curve,
        "trades":       trade_list,
    }

    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)

    print(f"Results saved to {output_path}")
