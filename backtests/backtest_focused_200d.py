"""Focused backtest comparison on the 200-day dataset."""
import logging
import sys
from pathlib import Path

logging.getLogger().setLevel(logging.CRITICAL)
logging.disable(logging.CRITICAL)

sys.path.insert(0, str(Path(__file__).parent.parent))

from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics

DATA_FILE = str(Path(__file__).parent.parent / "us30_m5_200d.csv")

base = dict(
    symbol="US30",
    timeframe_minutes=5,
    windows=[("10:00", "11:00"), ("11:00", "12:00")],
    one_trade_per_window=True,
    swing_lookback=3,
    sweep_lookback=10,
    spread_points=2.0,
    commission_per_trade=5.0,
    slippage_points=1.0,
    risk_per_trade=100.0,
    point_value=1.0,
    target_mode="rr",
    breakeven_r=0.0,
    trail_r=0.0,
    early_exit_r=0.0,
)

configs = []
for rr in [2.0, 3.0]:
    for fvg in [8.0, 15.0]:
        for entry in ["mid", "far_edge"]:
            for buf in [1.0, 3.0, 5.0]:
                for minrisk in [5.0, 10.0]:
                    configs.append(SilverBulletConfig(
                        **base,
                        rr=rr,
                        fvg_min_points=fvg,
                        entry_in_fvg=entry,
                        stop_buffer_points=buf,
                        min_risk_points=minrisk,
                    ))

print(f"Loading {DATA_FILE} ...")
df = prepare(DATA_FILE, configs[0])
print(f"  {len(df):,} bars loaded\n")

print(f"{'Config':<50} {'Trades':>6} {'Net P/L':>9} {'PF':>6} {'WR%':>6} {'Avg R':>7} {'Max DD':>8}")
print("-" * 110)

rows = []
for i, cfg in enumerate(configs, 1):
    trades = run_backtest(df, cfg)
    if not trades:
        continue
    m = compute_metrics(trades)
    name = f"rr={cfg.rr} fvg={cfg.fvg_min_points} entry={cfg.entry_in_fvg} buf={cfg.stop_buffer_points} minrisk={cfg.min_risk_points}"
    row = {
        "name": name,
        "cfg": cfg,
        "trades": m["num_trades"],
        "pnl": m["net_pnl_usd"],
        "pf": m["profit_factor"],
        "wr": m["win_rate_pct"],
        "avg_r": m["avg_r"],
        "dd": m["max_drawdown_usd"],
    }
    rows.append(row)
    pf_str = f"{row['pf']:.2f}" if isinstance(row['pf'], (int, float)) else " inf"
    print(f"{name:<50} {row['trades']:>6} ${row['pnl']:>8.2f} {pf_str:>6} {row['wr']:>5.1f}% {row['avg_r']:>7.3f} ${row['dd']:>7.2f}")

if rows:
    rows.sort(key=lambda r: r["pnl"], reverse=True)
    best = rows[0]
    print(f"\nBest by net P&L:")
    print(f"  {best['name']}")
    print(f"  Net P/L: ${best['pnl']:.2f}  PF: {best['pf']:.2f}  WR: {best['wr']:.1f}%  Trades: {best['trades']}")

    # Also show top 3 by profit factor with >20 trades
    pf_rows = [r for r in rows if r["trades"] >= 20]
    pf_rows.sort(key=lambda r: r["pf"] if r["pf"] is not None else 0, reverse=True)
    print("\nTop 3 by profit factor (>=20 trades):")
    for r in pf_rows[:3]:
        print(f"  PF={r['pf']:.2f}  ${r['pnl']:.2f}  {r['wr']:.1f}%  {r['trades']} trades | {r['name']}")
