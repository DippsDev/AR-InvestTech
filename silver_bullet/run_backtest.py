"""
CLI entry point.

Usage:
    python -m silver_bullet.run_backtest --data us30_m5.csv [options]

For full option list:
    python -m silver_bullet.run_backtest --help
"""
from __future__ import annotations

import sys
import os

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "silver_bullet"

import argparse

import pandas as pd

from .config import SilverBulletConfig
from .data import prepare
from .backtest import run_backtest
from .metrics import compute_metrics, print_metrics, trade_log_df, save_results_json
from .plot_results import plot_backtest


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Silver Bullet strategy backtester",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--data",     required=True,        help="Path to M5 OHLCV CSV")
    p.add_argument("--m1",       default=None,         help="Optional M1 CSV for entry refinement (future)")
    p.add_argument("--symbol",   default="US30")
    p.add_argument("--windows",  default="10:00-11:00,11:00-12:00,13:30-14:30",
                   help="Comma-separated NY windows, e.g. '10:00-11:00,11:00-12:00,13:30-14:30'")

    # Strategy knobs  (defaults = best config from grid search)
    p.add_argument("--swing-lookback",      type=int,   default=3)
    p.add_argument("--sweep-lookback",      type=int,   default=10)
    p.add_argument("--fvg-min-points",      type=float, default=8.0)
    p.add_argument("--entry-in-fvg",        default="mid",
                   choices=["near_edge", "mid", "far_edge"])
    p.add_argument("--stop-buffer",         type=float, default=1.0)
    p.add_argument("--target-mode",         default="opposite_liquidity",
                   choices=["rr", "opposite_liquidity"])
    p.add_argument("--rr",                  type=float, default=2.0)
    p.add_argument("--one-trade-per-window", action="store_true", default=True)
    p.add_argument("--min-risk",            type=float, default=5.0,
                   help="Minimum risk in points; degenerate setups below this are skipped")
    p.add_argument("--breakeven-r",         type=float, default=0.5,
                   help="Move stop to entry when price reaches this R multiple (0=disabled)")
    p.add_argument("--trail-r",             type=float, default=0.25,
                   help="After breakeven, trail stop this many R behind best price (0=disabled)")
    p.add_argument("--early-exit-r",        type=float, default=0.4,
                   help="Cut loss at this R multiple before breakeven triggers (0=disabled)")
    p.add_argument("--deep-profit-r",       type=float, default=2.0,
                   help="Switch to deep_trail_r once unrealised gain reaches this R multiple")
    p.add_argument("--deep-trail-r",        type=float, default=0.1,
                   help="Tight trail distance (R) when above deep_profit_r")
    p.add_argument("--use-daily-bias",       action="store_true", default=False,
                   help="Filter signals by previous-day candle direction (off by default for Silver Bullet)")
    p.add_argument("--skip-news-days",       action="store_true", default=False,
                   help="Skip signal generation on NFP/FOMC/CPI/GDP release days")
    p.add_argument("--news-rr",             type=float, default=5.0,
                   help="R:R target to use on high-impact news days (0=same as --rr)")

    # Cost / sizing
    p.add_argument("--spread",      type=float, default=2.0)
    p.add_argument("--commission",  type=float, default=5.0)
    p.add_argument("--slippage",    type=float, default=1.0)
    p.add_argument("--risk",        type=float, default=100.0,
                   help="USD risk per trade")
    p.add_argument("--point-value", type=float, default=1.0,
                   help="USD per index point per unit")

    # Output
    p.add_argument("--export-trades", default=None,
                   help="CSV path to save trade log (optional)")
    p.add_argument("--save-json", default=None,
                   help="JSON path to save full results (metrics + trades + equity curve)")
    p.add_argument("--show-trades",   type=int, default=10,
                   help="Number of example trades to print (0 = none)")
    p.add_argument("--plot",          action="store_true", default=False,
                   help="Show interactive performance dashboard chart")
    p.add_argument("--save-chart",    default=None,
                   help="Save chart to this image path (PNG/PDF/SVG) instead of displaying")

    return p.parse_args(argv)


def _parse_windows(raw: str) -> list[tuple[str, str]]:
    """Parse '10:00-11:00,11:00-12:00' into [('10:00','11:00'),...]."""
    result = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        parts = chunk.split("-")
        if len(parts) != 2:
            raise ValueError(f"Cannot parse window: {chunk!r}  (expected HH:MM-HH:MM)")
        result.append((parts[0].strip(), parts[1].strip()))
    return result


def main(argv=None):
    args = _parse_args(argv)

    cfg = SilverBulletConfig(
        symbol                = args.symbol,
        windows               = _parse_windows(args.windows),
        swing_lookback        = args.swing_lookback,
        sweep_lookback        = args.sweep_lookback,
        fvg_min_points        = args.fvg_min_points,
        entry_in_fvg          = args.entry_in_fvg,
        stop_buffer_points    = args.stop_buffer,
        target_mode           = args.target_mode,
        rr                    = args.rr,
        one_trade_per_window  = args.one_trade_per_window,
        min_risk_points       = args.min_risk,
        spread_points         = args.spread,
        commission_per_trade  = args.commission,
        slippage_points       = args.slippage,
        risk_per_trade        = args.risk,
        point_value           = args.point_value,
        breakeven_r           = args.breakeven_r,
        trail_r               = args.trail_r,
        early_exit_r          = args.early_exit_r,
        deep_profit_r         = args.deep_profit_r,
        deep_trail_r          = args.deep_trail_r,
        use_daily_bias        = args.use_daily_bias,
        skip_news_days        = args.skip_news_days,
        news_rr               = args.news_rr,
    )

    print(f"Loading data from {args.data} ...")
    df = prepare(args.data, cfg, m1_path=args.m1)
    print(f"  {len(df):,} bars loaded  "
          f"({df['timestamp_ny'].iloc[0].date()} to {df['timestamp_ny'].iloc[-1].date()})")
    window_bars = df["in_window"].sum()
    print(f"  {window_bars:,} bars inside configured windows")

    print("\nRunning backtest ...")
    trades = run_backtest(df, cfg)

    metrics = compute_metrics(trades)
    print_metrics(metrics)

    if trades and args.show_trades > 0:
        log = trade_log_df(trades)
        print(f"First {min(args.show_trades, len(trades))} trades:\n")
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 160)
        print(log.head(args.show_trades).to_string(index=False))
        print()

    if args.export_trades:
        log = trade_log_df(trades)
        log.to_csv(args.export_trades, index=False)
        print(f"Trade log saved to {args.export_trades}")

    if args.save_json:
        save_results_json(
            trades,
            metrics,
            cfg,
            output_path=args.save_json,
            data_file=args.data,
            df=df,
        )

    if args.plot or args.save_chart:
        plot_backtest(
            trades,
            metrics,
            show=args.plot,
            save_path=args.save_chart,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
