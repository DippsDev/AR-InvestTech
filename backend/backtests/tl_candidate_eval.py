"""Backtest the Trendline strategy on candidate symbols over the full
~17-month history (*_m5_max.csv, resampled to H1 internally), using the
current live TL config (split targets ON 3R/4R, BE 1.0R, trail 0.5R,
opposite_swing target with 3R floor) and per-symbol volatility-scaled
thresholds.

Scaling replicates multi_symbol_targets.py: scale = median M5 bar range /
24.9 (US30). USTECm uses its live TL_TARGETS overrides (3x touch
multiplier). XAUUSDm has no live overrides, so it is evaluated at both
the 1x base and the 3x multiplier used for the indices.

Usage: python backtests/tl_candidate_eval.py
"""
import json
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from trendline.config import TrendlineConfig
from trendline.data import prepare_from_m5
from trendline.backtest import run_backtest, BacktestCosts
from silver_bullet.metrics import compute_metrics

US30_MEDIAN_M5_RANGE = 24.9

COSTS = {  # from backtests/multi_sb_<sym>.json campaign configs
    "ustecm":  dict(spread=1.7606425702811248, slip=0.8803212851405624),
    "xauusdm": dict(spread=0.4566265060240964, slip=0.2283132530120482),
}


def median_m5_range(short: str) -> float:
    df = pd.read_csv(f"data/{short}_m5_max.csv")
    return float((df["high"] - df["low"]).median())


def run(short: str, symbol: str, touch_mult: float):
    c = COSTS[short]
    scale = median_m5_range(short) / US30_MEDIAN_M5_RANGE
    cfg = TrendlineConfig(
        symbol=symbol,
        obstruction_tolerance_points=3.0 * touch_mult * scale,
        touch_tolerance_points=3.0 * touch_mult * scale,
        breach_tolerance_points=5.0 * scale,
        stop_buffer_points=5.0 * scale,
        min_risk_points=15.0 * scale,
        skip_news_days=True,
        # split_targets stays at its live default (True, 3R/4R)
    )
    costs = BacktestCosts(
        spread_points=c["spread"],
        slippage_points=c["slip"],
        commission_per_trade=5.0,
        risk_per_trade=100.0,
        point_value=1.0,
    )
    df = prepare_from_m5(f"data/{short}_m5_max.csv")
    trades = run_backtest(df, cfg, costs)
    m = compute_metrics(trades)
    print(f"{symbol:<9} {touch_mult:>3.0f}x {scale:>7.3f} {m['num_trades']:>6} "
          f"{m['win_rate_pct']:>5.1f}% {m['net_pnl_usd']:>10.2f} "
          f"{m['profit_factor']:>8.2f} {m['max_drawdown_usd']:>9.2f} "
          f"{m['trades_per_day']:>7.2f}  "
          f"[{df['timestamp_ny'].iloc[0].date()} -> {df['timestamp_ny'].iloc[-1].date()}]")


print(f"\n{'Symbol':<9} {'Mult':>4} {'Scale':>7} {'Trades':>6} {'Win%':>6} "
      f"{'Net P&L':>10} {'ProfitF':>8} {'MaxDD':>9} {'Tr/Day':>7}  Range")
print("-" * 86)
which = sys.argv[1] if len(sys.argv) > 1 else "all"
if which in ("ustecm", "all"):
    run("ustecm", "USTECm", 3.0)
if which in ("xauusdm", "all"):
    run("xauusdm", "XAUUSDm", 1.0)
    run("xauusdm", "XAUUSDm", 3.0)
if which != "all":
    sys.exit(0)

# Live TL symbols for reference (their TL_TARGETS overrides, 180d campaign
# metrics from multi_tl_*.json and full-history multimax_tl_*.json):
print("\nLive TL symbols (reference):")
for short, sym in [("de30m", "DE30m"), ("usdjpym", "USDJPYm")]:
    for pref, label in [("multi_tl", "180d"), ("multimax_tl", "max")]:
        try:
            m = json.load(open(f"backtests/{pref}_{short}.json"))["metrics"]
            print(f"  {sym:<8} {label:<5} trades={m['num_trades']:>3}  PF={m['profit_factor']:.2f}  "
                  f"net=${m['net_pnl_usd']:.0f}  win={m['win_rate_pct']:.1f}%")
        except FileNotFoundError:
            pass
for pref, label in [("multi_tl", "180d"), ("multimax_tl", "max")]:
    try:
        m = json.load(open(f"backtests/{pref}_ustecm.json"))["metrics"]
        print(f"  USTECm   {label:<5} trades={m['num_trades']:>3}  PF={m['profit_factor']:.2f}  "
              f"net=${m['net_pnl_usd']:.0f}  win={m['win_rate_pct']:.1f}%  (existing campaign run)")
    except FileNotFoundError:
        pass
