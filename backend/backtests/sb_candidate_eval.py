"""Backtest Silver Bullet on candidate symbols (USTECm, XAUUSDm) using the
full ~17-month M5 history (*_m5_max.csv), each symbol's campaign thresholds
and costs from backtests/multi_sb_<sym>.json, and the CURRENT live config
(split_targets=False / liquidity target, skip_news_days=True, BE 0.25R,
trail 0.1R, early exit 0.4R, deep trail).

Usage: python backtests/sb_candidate_eval.py USTECm XAUUSDm
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics

SYMS = sys.argv[1:] or ["USTECm", "XAUUSDm"]

print(f"\n{'Symbol':<9} {'Trades':>6} {'Win%':>6} {'Net P&L':>10} {'ProfitF':>8} {'MaxDD':>9} {'Tr/Day':>7}  Range")
print("-" * 78)
for symbol in SYMS:
    short = symbol.lower()
    camp = json.load(open(f"backtests/multi_sb_{short}.json"))
    c = camp["config"]
    cfg = SilverBulletConfig(
        symbol=symbol,
        fvg_min_points=c["fvg_min_points"],
        stop_buffer_points=c["stop_buffer_points"],
        min_risk_points=c["min_risk_points"],
        spread_points=c["spread_points"],
        commission_per_trade=c["commission_per_trade"],
        slippage_points=c["slippage_points"],
        risk_per_trade=c["risk_per_trade"],
        point_value=c["point_value"],
        split_targets=False,          # current live setting (liquidity target)
        skip_news_days=True,
    )
    df = prepare(f"data/{short}_m5_max.csv", cfg)
    trades = run_backtest(df, cfg)
    m = compute_metrics(trades)
    print(f"{symbol:<9} {m['num_trades']:>6} {m['win_rate_pct']:>5.1f}% "
          f"{m['net_pnl_usd']:>10.2f} {m['profit_factor']:>8.2f} {m['max_drawdown_usd']:>9.2f} "
          f"{m['trades_per_day']:>7.2f}  "
          f"[{df['timestamp_ny'].iloc[0].date()} -> {df['timestamp_ny'].iloc[-1].date()}]")
    # campaign 180d reference for context
    cm = camp.get("metrics", {})
    if cm:
        print(f"  (180d campaign ref: trades={cm.get('num_trades', cm.get('total_trades'))}, "
              f"PF={cm.get('profit_factor')})")
