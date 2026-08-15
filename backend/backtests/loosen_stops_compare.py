"""Compare current live SB trade management vs loosened variants, on the
full ~17-month M5 history for all four live SB symbols, using each symbol's
campaign thresholds/costs and the current live config otherwise
(split_targets=False, skip_news_days=True).

Current live: BE 0.25R, trail 0.1R, early exit 0.4R, deep trail 0.1R @2R
Variant LOOSE:  BE 0.5R,  trail 0.25R, early exit disabled, deep trail 0.25R @2R
Variant LOOSER: BE 0.75R, trail 0.5R,  early exit disabled, deep trail 0.5R @3R
"""
import json
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics

SYMS = ["de30m", "eurusdm", "gbpusdm", "xauusdm"]
if len(sys.argv) > 1:
    SYMS = [sys.argv[1]]
ARMS = {
    "LIVE":   dict(),  # current defaults
    "LOOSE":  dict(breakeven_r=0.5, trail_r=0.25, early_exit_r=0.0,
                   deep_profit_r=2.0, deep_trail_r=0.25),
    "LOOSER": dict(breakeven_r=0.75, trail_r=0.5, early_exit_r=0.0,
                   deep_profit_r=3.0, deep_trail_r=0.5),
}

totals = {arm: 0.0 for arm in ARMS}
print(f"\n{'Symbol':<9} {'Arm':<7} {'Trades':>6} {'Win%':>6} {'Net P&L':>10} {'ProfitF':>8} {'MaxDD':>9}")
print("-" * 62)
for short in SYMS:
    c = json.load(open(f"backtests/multi_sb_{short}.json"))["config"]
    base = SilverBulletConfig(
        symbol=short.upper(),
        fvg_min_points=c["fvg_min_points"],
        stop_buffer_points=c["stop_buffer_points"],
        min_risk_points=c["min_risk_points"],
        spread_points=c["spread_points"],
        commission_per_trade=c["commission_per_trade"],
        slippage_points=c["slippage_points"],
        split_targets=False,
        skip_news_days=True,
    )
    df = prepare(f"data/{short}_m5_max.csv", base)
    for arm, ov in ARMS.items():
        cfg = replace(base, **ov)
        m = compute_metrics(run_backtest(df, cfg))
        totals[arm] += m["net_pnl_usd"]
        print(f"{short.upper():<9} {arm:<7} {m['num_trades']:>6} {m['win_rate_pct']:>5.1f}% "
              f"{m['net_pnl_usd']:>10.2f} {m['profit_factor']:>8.2f} {m['max_drawdown_usd']:>9.2f}")
print("-" * 62)
for arm, tot in totals.items():
    print(f"COMBINED  {arm:<7} {'':>6} {'':>6} {tot:>10.2f}")
