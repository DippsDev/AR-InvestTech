"""
CLI entry point for the Mutanabby backtester.

Usage:
    python -m mutanabby.run_backtest --data data/us30_m5_max.csv

For full option list:
    python -m mutanabby.run_backtest --help
"""
from __future__ import annotations

import sys
import os

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "mutanabby"

import argparse
import json

import pandas as pd

from .config import MutanabbyConfig
from .data import prepare
from .backtest import BacktestCosts, run_backtest
from silver_bullet.metrics import compute_metrics


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Mutanabby 'Ultimate Algo' backtester (SuperTrend flip + SMA filter)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--data", required=True, help="Path to M5 OHLCV CSV")
    p.add_argument("--timeframe", default=None,
                   help="Pandas offset to resample to (e.g. 15min, 1h, 4h). Omit for native M5.")

    p.add_argument("--sensitivity",     type=float, default=MutanabbyConfig.sensitivity)
    p.add_argument("--st-atr-length",   type=int,   default=MutanabbyConfig.supertrend_atr_length)
    p.add_argument("--trend-sma",       type=int,   default=MutanabbyConfig.trend_sma_length)
    p.add_argument("--risk-atr-length", type=int,   default=MutanabbyConfig.risk_atr_length)
    p.add_argument("--atr-multiplier",  type=float, default=MutanabbyConfig.atr_risk_multiplier)
    p.add_argument("--rr",              type=float, default=MutanabbyConfig.rr,
                   help="Which R rung to target (indicator draws 1, 2 and 3)")
    p.add_argument("--min-risk",        type=float, default=MutanabbyConfig.min_risk_points)
    p.add_argument("--breakeven-r",     type=float, default=MutanabbyConfig.breakeven_r)
    p.add_argument("--trail-r",         type=float, default=MutanabbyConfig.trail_r)
    p.add_argument("--exit-on-opposite", action="store_true",
                   default=MutanabbyConfig.exit_on_opposite_signal,
                   help="Close (and reverse) when the opposite signal fires")
    p.add_argument("--skip-news-days",  action="store_true", default=MutanabbyConfig.skip_news_days)

    # Cost / sizing (backtest-only)
    p.add_argument("--spread",      type=float, default=2.0)
    p.add_argument("--commission",  type=float, default=5.0)
    p.add_argument("--slippage",    type=float, default=1.0)
    p.add_argument("--risk",        type=float, default=100.0, help="USD risk per trade")
    p.add_argument("--point-value", type=float, default=1.0)

    p.add_argument("--show-trades", type=int, default=10, help="Number of example trades to print (0 = none)")
    p.add_argument("--save-json",   default=None, help="JSON path to save full results")
    p.add_argument("--quiet",       action="store_true", help="Print the summary block only")

    return p.parse_args(argv)


def main(argv=None):
    args = _parse_args(argv)

    cfg = MutanabbyConfig(
        sensitivity             = args.sensitivity,
        supertrend_atr_length   = args.st_atr_length,
        trend_sma_length        = args.trend_sma,
        risk_atr_length         = args.risk_atr_length,
        atr_risk_multiplier     = args.atr_multiplier,
        rr                      = args.rr,
        min_risk_points         = args.min_risk,
        breakeven_r             = args.breakeven_r,
        trail_r                 = args.trail_r,
        exit_on_opposite_signal = args.exit_on_opposite,
        skip_news_days          = args.skip_news_days,
    )
    costs = BacktestCosts(
        spread_points        = args.spread,
        commission_per_trade = args.commission,
        slippage_points      = args.slippage,
        risk_per_trade       = args.risk,
        point_value          = args.point_value,
    )

    tf_note = args.timeframe or "M5 (native)"
    if not args.quiet:
        print(f"Loading data from {args.data}  [{tf_note}] ...")
    df = prepare(args.data, args.timeframe)
    if not args.quiet:
        print(f"  {len(df):,} bars  ({df['timestamp_ny'].iloc[0].date()} to {df['timestamp_ny'].iloc[-1].date()})")
        print("\nRunning backtest ...")

    trades = run_backtest(df, cfg, costs)
    metrics = compute_metrics(trades)

    print("\n" + "=" * 50)
    print("  MUTANABBY BACKTEST RESULTS")
    print("=" * 50)
    print(f"  Data            : {os.path.basename(args.data)}  [{tf_note}]")
    print(f"  Params          : sens={cfg.sensitivity} stAtr={cfg.supertrend_atr_length} "
          f"sma={cfg.trend_sma_length} rr={cfg.rr} flip={cfg.exit_on_opposite_signal}")
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
    print(f"  Exit breakdown  : target={exits.get('target',0)}  stop={exits.get('stop',0)}  "
          f"flip={exits.get('opposite_signal',0)}  time={exits.get('time_exit',0)}")
    print("=" * 50 + "\n")

    if trades and args.show_trades > 0 and not args.quiet:
        rows = [{
            "trade_id": t.trade_id, "date": t.date, "direction": t.direction,
            "strength": t.strength,
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
            "meta": {
                "data_file": args.data,
                "timeframe": tf_note,
                "bars": int(len(df)),
                "date_range": {
                    "start": str(df["timestamp_ny"].iloc[0].date()),
                    "end":   str(df["timestamp_ny"].iloc[-1].date()),
                },
            },
            "config": {
                "sensitivity": cfg.sensitivity,
                "supertrend_atr_length": cfg.supertrend_atr_length,
                "trend_sma_length": cfg.trend_sma_length,
                "risk_atr_length": cfg.risk_atr_length,
                "atr_risk_multiplier": cfg.atr_risk_multiplier,
                "rr": cfg.rr,
                "min_risk_points": cfg.min_risk_points,
                "breakeven_r": cfg.breakeven_r,
                "trail_r": cfg.trail_r,
                "exit_on_opposite_signal": cfg.exit_on_opposite_signal,
                "skip_news_days": cfg.skip_news_days,
                "spread_points": costs.spread_points,
                "commission_per_trade": costs.commission_per_trade,
                "slippage_points": costs.slippage_points,
                "risk_per_trade": costs.risk_per_trade,
                "point_value": costs.point_value,
            },
            "metrics": metrics,
            "trades": [{
                "trade_id": t.trade_id, "date": t.date, "direction": t.direction,
                "strength": t.strength, "rsi_at_signal": None if pd.isna(t.rsi_at_signal) else round(t.rsi_at_signal, 2),
                "entry_time": str(t.entry_time), "entry_price": t.entry_price,
                "stop_price": t.stop_price, "target_price": t.target_price,
                "exit_time": str(t.exit_time), "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
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
