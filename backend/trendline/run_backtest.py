"""
CLI entry point for the Trendline backtester.

Usage:
    python -m trendline.run_backtest --data data/us30_m5_current.csv

For full option list:
    python -m trendline.run_backtest --help
"""
from __future__ import annotations

import sys
import os

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "trendline"

import argparse
import json

import pandas as pd

from .config import TrendlineConfig
from .data import prepare_from_m5
from .backtest import BacktestCosts, run_backtest
from silver_bullet.metrics import compute_metrics


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Trendline strategy backtester (H1, resampled from stored M5 history)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--data", required=True, help="Path to M5 OHLCV CSV (resampled to H1 internally)")

    p.add_argument("--swing-lookback",        type=int,   default=TrendlineConfig.swing_lookback)
    p.add_argument("--avg-range-lookback",    type=int,   default=TrendlineConfig.avg_range_lookback)
    p.add_argument("--steepness-max-ratio",   type=float, default=TrendlineConfig.steepness_max_ratio)
    p.add_argument("--obstruction-tolerance", type=float, default=TrendlineConfig.obstruction_tolerance_points)
    p.add_argument("--breach-tolerance",      type=float, default=TrendlineConfig.breach_tolerance_points)
    p.add_argument("--touch-tolerance",       type=float, default=TrendlineConfig.touch_tolerance_points)
    p.add_argument("--stop-buffer",           type=float, default=TrendlineConfig.stop_buffer_points)
    p.add_argument("--min-risk",              type=float, default=TrendlineConfig.min_risk_points)
    p.add_argument("--target-mode",           default=TrendlineConfig.target_mode, choices=["opposite_swing", "rr"])
    p.add_argument("--rr",                    type=float, default=TrendlineConfig.rr)
    p.add_argument("--no-split-targets", dest="split_targets", action="store_false",
                   help="Disable the TP1/TP2 split and use the single --target-mode/--rr target")
    p.set_defaults(split_targets=TrendlineConfig.split_targets)
    p.add_argument("--tp1-rr",       type=float, default=TrendlineConfig.tp1_rr)
    p.add_argument("--tp2-rr",       type=float, default=TrendlineConfig.tp2_rr)
    p.add_argument("--tp1-fraction", type=float, default=TrendlineConfig.tp1_fraction,
                   help="Portion of the position closed at TP1 (rest rides to TP2)")
    p.add_argument("--min-rr-for-swing",      type=float, default=TrendlineConfig.min_rr_for_swing_target)
    p.add_argument("--breakeven-r",           type=float, default=TrendlineConfig.breakeven_r)
    p.add_argument("--trail-r",               type=float, default=TrendlineConfig.trail_r)
    p.add_argument("--skip-news-days",        action="store_true", default=TrendlineConfig.skip_news_days)

    # Cost / sizing (backtest-only — Trendline's live config has no such fields)
    p.add_argument("--spread",      type=float, default=2.0)
    p.add_argument("--commission",  type=float, default=5.0)
    p.add_argument("--slippage",    type=float, default=1.0)
    p.add_argument("--risk",        type=float, default=100.0, help="USD risk per trade")
    p.add_argument("--point-value", type=float, default=1.0)

    p.add_argument("--show-trades", type=int, default=10, help="Number of example trades to print (0 = none)")
    p.add_argument("--save-json",   default=None, help="JSON path to save full results")

    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    cfg = TrendlineConfig(
        swing_lookback              = args.swing_lookback,
        avg_range_lookback          = args.avg_range_lookback,
        steepness_max_ratio         = args.steepness_max_ratio,
        obstruction_tolerance_points= args.obstruction_tolerance,
        breach_tolerance_points     = args.breach_tolerance,
        touch_tolerance_points      = args.touch_tolerance,
        stop_buffer_points          = args.stop_buffer,
        min_risk_points             = args.min_risk,
        target_mode                 = args.target_mode,
        rr                          = args.rr,
        split_targets               = args.split_targets,
        tp1_rr                      = args.tp1_rr,
        tp2_rr                      = args.tp2_rr,
        tp1_fraction                = args.tp1_fraction,
        min_rr_for_swing_target     = args.min_rr_for_swing,
        breakeven_r                 = args.breakeven_r,
        trail_r                     = args.trail_r,
        skip_news_days              = args.skip_news_days,
    )
    costs = BacktestCosts(
        spread_points        = args.spread,
        commission_per_trade = args.commission,
        slippage_points       = args.slippage,
        risk_per_trade        = args.risk,
        point_value           = args.point_value,
    )

    print(f"Loading data from {args.data} (resampling M5 -> H1) ...")
    df = prepare_from_m5(args.data)
    print(f"  {len(df):,} H1 bars  ({df['timestamp_ny'].iloc[0].date()} to {df['timestamp_ny'].iloc[-1].date()})")

    print("\nRunning backtest ...")
    trades = run_backtest(df, cfg, costs)

    metrics = compute_metrics(trades)
    print("\n" + "=" * 50)
    print("  TRENDLINE BACKTEST RESULTS")
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
    exits = metrics["exit_breakdown"]
    # tp1 counts trades whose first leg filled, whatever took the runner after —
    # it is not an exit reason of its own, so it is reported alongside rather
    # than inside the breakdown (which must still sum to the trade count).
    tp1_filled = sum(1 for t in trades if t.tp1_hit)
    print(f"  Exit breakdown  : target={exits.get('target',0)}  target2={exits.get('target2',0)}  "
          f"stop={exits.get('stop',0)}  time={exits.get('time_exit',0)}")
    if tp1_filled:
        print(f"  TP1 partials    : {tp1_filled} of {len(trades)} trades banked their first leg")
    print("=" * 50 + "\n")

    if trades and args.show_trades > 0:
        rows = [{
            "trade_id": t.trade_id, "date": t.date, "direction": t.direction,
            "pattern": t.pattern, "line_kind": t.line_kind,
            "entry_price": round(t.entry_price, 2), "stop_price": round(t.stop_price, 2),
            "target_price": round(t.target_price, 2), "exit_reason": t.exit_reason,
            "r_multiple": round(t.r_multiple, 3) if t.r_multiple is not None else None,
            "pnl_usd": round(t.pnl_dollars, 2) if t.pnl_dollars is not None else None,
        } for t in trades[:args.show_trades]]
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 160)
        print(f"First {len(rows)} trades:\n")
        print(pd.DataFrame(rows).to_string(index=False))
        print()

    if args.save_json:
        payload = {
            "metrics": metrics,
            "trades": [{
                "trade_id": t.trade_id, "date": t.date, "direction": t.direction,
                "entry_time": str(t.entry_time), "entry_price": t.entry_price,
                "stop_price": t.stop_price, "target_price": t.target_price,
                "exit_time": str(t.exit_time), "exit_price": t.exit_price,
                "exit_reason": t.exit_reason, "line_kind": t.line_kind, "pattern": t.pattern,
                "risk_points": round(t.risk_points, 2),
                "r_multiple": round(t.r_multiple, 3) if t.r_multiple is not None else None,
                "pnl_usd": round(t.pnl_dollars, 2) if t.pnl_dollars is not None else None,
            } for t in trades],
        }
        with open(args.save_json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        print(f"Results saved to {args.save_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
