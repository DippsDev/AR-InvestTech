"""Focused Silver Bullet optimizer for the 3-year dataset.
Tests the most impactful parameters only, so it finishes quickly."""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

logging.disable(logging.WARNING)

sys.path.insert(0, str(Path(__file__).parent.parent))

from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics

DATA_FILE = str(Path(__file__).parent.parent / "us30_m5_3y.csv")
OUT_FILE = str(Path(__file__).parent / "backtest_optimization_focused.json")

PARAM_GRID = {
    "rr":                 [2.0, 3.0],
    "fvg_min_points":     [5.0, 10.0, 15.0],
    "entry_in_fvg":       ["mid", "far_edge"],
    "stop_buffer_points": [1.0, 3.0, 5.0],
    "min_risk_points":    [5.0, 10.0],
}

# Each combo of trade-management settings
TRADE_MGMT = [
    {"breakeven_r": 0.5, "trail_r": 0.25, "early_exit_r": 0.4},
    {"breakeven_r": 0.0, "trail_r": 0.0, "early_exit_r": 0.0},
]

FIXED = dict(
    symbol="US30",
    timeframe_minutes=5,
    windows=[("10:00", "11:00"), ("11:00", "12:00")],
    one_trade_per_window=True,
    target_mode="rr",
    swing_lookback=3,
    sweep_lookback=10,
    spread_points=2.0,
    commission_per_trade=5.0,
    slippage_points=1.0,
    risk_per_trade=100.0,
    point_value=1.0,
)


def score(m: dict) -> float:
    pf = m["profit_factor"]
    pnl = m["net_pnl_usd"]
    dd = max(m["max_drawdown_usd"], 1.0)
    avg_r = m["avg_r"]
    if pf is None:
        return -999
    if pf >= 1.0 and pnl > 0:
        return (pnl / dd) * 0.5 + (pf - 1.0) * 0.3 + avg_r * 0.2
    return pnl / 1000.0


def main():
    print(f"Loading {DATA_FILE} ...")
    base_cfg = SilverBulletConfig(**FIXED)
    df = prepare(DATA_FILE, base_cfg)
    print(f"  {len(df):,} bars loaded")
    print(f"  {df['in_window'].sum():,} bars inside windows\n")

    param_keys = list(PARAM_GRID.keys())
    param_values = list(PARAM_GRID.values())
    param_combos = [dict(zip(param_keys, v)) for v in product(*param_values)]
    total = len(param_combos) * len(TRADE_MGMT)

    print(f"Running {total} combinations ...\n")

    results = []
    t0 = time.perf_counter()

    for i, p in enumerate(param_combos, 1):
        for tm in TRADE_MGMT:
            params = {**p, **tm}
            cfg = SilverBulletConfig(**{**FIXED, **params})
            trades = run_backtest(df, cfg)
            if not trades:
                continue
            m = compute_metrics(trades)
            if m["num_trades"] < 15:
                continue
            results.append({
                "params": params,
                "metrics": {
                    "num_trades": m["num_trades"],
                    "net_pnl_usd": m["net_pnl_usd"],
                    "win_rate_pct": m["win_rate_pct"],
                    "avg_r": m["avg_r"],
                    "expectancy_usd": m["expectancy_usd"],
                    "profit_factor": m["profit_factor"],
                    "max_drawdown_usd": m["max_drawdown_usd"],
                    "exit_breakdown": m["exit_breakdown"],
                },
                "score": round(score(m), 4),
            })

        if i % 5 == 0 or i == len(param_combos):
            elapsed = time.perf_counter() - t0
            pct = (i * len(TRADE_MGMT)) / total * 100
            print(f"  [{i}/{len(param_combos)}] {pct:.1f}%  valid={len(results)}  elapsed={elapsed:.0f}s")

    elapsed = time.perf_counter() - t0
    print(f"\nDone in {elapsed:.1f}s. Valid configs: {len(results)}\n")

    if not results:
        print("No valid configurations found.")
        return

    results.sort(key=lambda r: r["score"], reverse=True)

    print("Top 10 configs:\n")
    print(f"{'Rank':>4} {'Net P/L':>9} {'PF':>6} {'WR%':>6} {'AvgR':>7} {'MaxDD':>8} {'Trades':>7} {'Score':>8} Params")
    print("-" * 130)
    for rank, r in enumerate(results[:10], 1):
        m = r["metrics"]
        p = r["params"]
        param_str = (
            f"rr={p['rr']} fvg={p['fvg_min_points']} entry={p['entry_in_fvg']} "
            f"buf={p['stop_buffer_points']} minrisk={p['min_risk_points']} "
            f"be={p['breakeven_r']} trail={p['trail_r']}"
        )
        pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else " inf"
        print(f"{rank:>4} ${m['net_pnl_usd']:>8.2f} {pf:>6} {m['win_rate_pct']:>5.1f}% {m['avg_r']:>7.3f} ${m['max_drawdown_usd']:>7.2f} {m['num_trades']:>7} {r['score']:>8.4f} {param_str}")

    with open(OUT_FILE, "w", encoding="utf-8") as fh:
        json.dump({
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "data_file": DATA_FILE,
                "total_combos": total,
                "valid_combos": len(results),
            },
            "top_configs": results[:20],
        }, fh, indent=2, default=str)

    print(f"\nFull results saved to {OUT_FILE}")


if __name__ == "__main__":
    main()
