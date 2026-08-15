"""Compare split_targets ON (current live config) vs OFF (measured-edge config)
for each live Silver Bullet symbol, on the full ~17-month M5 history
(*_m5_max.csv), using each symbol's campaign thresholds and costs from
backend/backtests/multi_sb_<sym>.json plus SilverBulletConfig defaults for
trade management (BE 0.25R, trail 0.1R, early exit 0.4R, deep trail).
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

SYMS = {"DE30m": "de30m", "EURUSDm": "eurusdm", "GBPUSDm": "gbpusdm"}
if len(sys.argv) > 1:
    SYMS = {sys.argv[1]: SYMS[sys.argv[1]]}

rows = []
for symbol, short in SYMS.items():
    camp = json.load(open(f"backtests/multi_sb_{short}.json"))
    c = camp["config"]
    base = SilverBulletConfig(
        symbol=symbol,
        fvg_min_points=c["fvg_min_points"],
        stop_buffer_points=c["stop_buffer_points"],
        min_risk_points=c["min_risk_points"],
        spread_points=c["spread_points"],
        commission_per_trade=c["commission_per_trade"],
        slippage_points=c["slippage_points"],
        risk_per_trade=c["risk_per_trade"],
        point_value=c["point_value"],
        skip_news_days=True,
    )
    data_path = f"data/{short}_m5_max.csv"
    for split in (True, False):
        cfg = replace(base, split_targets=split)
        df = prepare(data_path, cfg)
        trades = run_backtest(df, cfg)
        m = compute_metrics(trades)
        rows.append((symbol, "SPLIT 3R/4R" if split else "LIQUIDITY", m, df))

print(f"\n{'Symbol':<9} {'Mode':<12} {'Trades':>6} {'Win%':>6} {'Net P&L':>10} {'ProfitF':>8} {'MaxDD':>9}")
print("-" * 64)
for symbol, mode, m, df in rows:
    print(f"{symbol:<9} {mode:<12} {m['num_trades']:>6} {m['win_rate_pct']:>5.1f}% "
          f"{m['net_pnl_usd']:>10.2f} {m['profit_factor']:>8.2f} {m['max_drawdown_usd']:>9.2f}  "
          f"[{df['timestamp_ny'].iloc[0].date()} -> {df['timestamp_ny'].iloc[-1].date()}]")
