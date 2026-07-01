"""Quiet comparison of Silver Bullet configs (logs suppressed)."""
import logging
import sys
from pathlib import Path

# CRITICAL must be set before any strategy imports
logging.getLogger().setLevel(logging.CRITICAL)
logging.disable(logging.CRITICAL)

sys.path.insert(0, str(Path(__file__).parent.parent))

from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics

DATA_FILE = str(Path(__file__).parent.parent / "us30_m5_3y.csv")

# Two-window default (matches silver_bullet/config.py)
cfg_2win = SilverBulletConfig(
    windows=[("10:00", "11:00"), ("11:00", "12:00")],
    swing_lookback=3,
    sweep_lookback=10,
    fvg_min_points=8.0,
    entry_in_fvg="near_edge",
    stop_buffer_points=1.0,
    target_mode="opposite_liquidity",
    rr=2.0,
    one_trade_per_window=True,
    min_risk_points=5.0,
    breakeven_r=0.5,
    trail_r=0.25,
    early_exit_r=0.4,
    spread_points=2.0,
    commission_per_trade=5.0,
    slippage_points=1.0,
    risk_per_trade=100.0,
    point_value=1.0,
)

# Three-window default (matches run_backtest.py)
cfg_3win = SilverBulletConfig(
    windows=[("10:00", "11:00"), ("11:00", "12:00"), ("13:30", "14:30")],
    swing_lookback=3,
    sweep_lookback=10,
    fvg_min_points=8.0,
    entry_in_fvg="mid",
    stop_buffer_points=1.0,
    target_mode="opposite_liquidity",
    rr=2.0,
    one_trade_per_window=True,
    min_risk_points=5.0,
    breakeven_r=0.5,
    trail_r=0.25,
    early_exit_r=0.4,
    spread_points=2.0,
    commission_per_trade=5.0,
    slippage_points=1.0,
    risk_per_trade=100.0,
    point_value=1.0,
)

cfg_2win_mid = SilverBulletConfig(**{**cfg_2win.__dict__, "entry_in_fvg": "mid"})
cfg_3win_near = SilverBulletConfig(**{**cfg_3win.__dict__, "entry_in_fvg": "near_edge"})

configs = {
    "2win_near_edge": cfg_2win,
    "3win_mid": cfg_3win,
    "2win_mid": cfg_2win_mid,
    "3win_near_edge": cfg_3win_near,
}

print(f"Loading {DATA_FILE} ...")
df = prepare(DATA_FILE, cfg_2win)
print(f"  {len(df):,} bars loaded\n")

print(f"{'Config':<20} {'Trades':>6} {'Net P/L':>9} {'PF':>6} {'WR%':>6} {'Avg R':>7} {'Max DD':>8} {'Stop':>5} {'Tgt':>4} {'Time':>4}")
print("-" * 95)

rows = []
for name, cfg in configs.items():
    trades = run_backtest(df, cfg)
    if not trades:
        print(f"{name:<20} NO TRADES")
        continue
    m = compute_metrics(trades)
    exits = m.get("exit_breakdown", {})
    row = {
        "name": name,
        "trades": m["num_trades"],
        "pnl": m["net_pnl_usd"],
        "pf": m["profit_factor"],
        "wr": m["win_rate_pct"],
        "avg_r": m["avg_r"],
        "dd": m["max_drawdown_usd"],
        "stop": exits.get("stop", 0),
        "target": exits.get("target", 0),
        "time": exits.get("time", 0),
    }
    rows.append(row)
    pf_str = f"{row['pf']:.2f}" if isinstance(row['pf'], (int, float)) else " inf"
    print(f"{name:<20} {row['trades']:>6} ${row['pnl']:>8.2f} {pf_str:>6} {row['wr']:>5.1f}% {row['avg_r']:>7.3f} ${row['dd']:>7.2f} {row['stop']:>5} {row['target']:>4} {row['time']:>4}")

best = max(rows, key=lambda r: r["pnl"])
print(f"\nBest by net P&L: {best['name']} (${best['pnl']:.2f})")
