"""
Silver Bullet parameter optimizer.

Grid-searches key strategy parameters, ranks every combination by a
Calmar-style composite score, and writes results to backtest_optimization.json.

Usage:
    python optimize.py [--data us30_m5_200d.csv] [--out backtest_optimization.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime, timezone
from itertools import product

from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import load_csv, add_ny_time, add_window_id
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics

# Silence trade-level logs during the sweep — they flood the console
logging.disable(logging.WARNING)

# ── Parameter grid ────────────────────────────────────────────────────────────
PARAM_GRID: dict[str, list] = {
    "rr":                 [1.0, 1.5, 2.0, 2.5, 3.0],
    "fvg_min_points":     [3.0, 5.0, 10.0],
    "entry_in_fvg":       ["near_edge", "mid", "far_edge"],
    "min_risk_points":    [5.0, 15.0],
    "swing_lookback":     [2, 3, 5],
    "sweep_lookback":     [10, 20],
    "stop_buffer_points": [1.0, 3.0, 5.0],
}

# Fixed parameters (not varied)
FIXED_PARAMS = dict(
    symbol               = "US30",
    timeframe_minutes    = 5,
    windows              = [("10:00", "11:00"), ("11:00", "12:00")],
    one_trade_per_window = True,
    spread_points        = 2.0,
    commission_per_trade = 5.0,
    slippage_points      = 1.0,
    risk_per_trade       = 100.0,
    point_value          = 1.0,
    target_mode          = "rr",
)

MIN_TRADES = 15   # discard configs with fewer trades (too little data)


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score(m: dict) -> float:
    """
    Composite score that rewards:
      - High profit factor (primary gate for profitability)
      - Positive net P&L scaled by max drawdown (Calmar-style)
      - Good average R

    Unprofitable configs get a large negative score based on net P&L.
    """
    pf  = m["profit_factor"] if isinstance(m["profit_factor"], (int, float)) else 999.0
    pnl = m["net_pnl_usd"]
    dd  = max(m["max_drawdown_usd"], 1.0)
    avg_r = m["avg_r"]

    if pf >= 1.0 and pnl > 0:
        calmar = pnl / dd
        return calmar * 0.5 + (pf - 1.0) * 0.3 + avg_r * 0.2
    else:
        return pnl / 1000.0  # negative, scaled


# ── Per-combination runner ────────────────────────────────────────────────────

def _run_combo(params: dict, df) -> dict | None:
    cfg = SilverBulletConfig(**{**FIXED_PARAMS, **params})
    trades = run_backtest(df, cfg)
    if not trades:
        return None
    m = compute_metrics(trades)
    if m["num_trades"] < MIN_TRADES:
        return None

    pf_val = m["profit_factor"]
    return {
        "params":  params,
        "metrics": {
            "num_trades":       m["num_trades"],
            "net_pnl_usd":      m["net_pnl_usd"],
            "win_rate_pct":     m["win_rate_pct"],
            "avg_r":            m["avg_r"],
            "expectancy_usd":   m["expectancy_usd"],
            "profit_factor":    pf_val if isinstance(pf_val, (int, float)) else None,
            "max_drawdown_usd": m["max_drawdown_usd"],
            "gross_profit_usd": m["gross_profit_usd"],
            "gross_loss_usd":   m["gross_loss_usd"],
            "trades_per_day":   m["trades_per_day"],
            "exit_breakdown":   m["exit_breakdown"],
        },
        "score": round(_score(m), 4),
    }


# ── Sensitivity analysis ──────────────────────────────────────────────────────

def _sensitivity(results: list[dict]) -> dict:
    """
    For each parameter, compute: mean score per unique value.
    Helps identify which knobs matter most.
    """
    param_keys = list(PARAM_GRID.keys())
    sensitivity: dict[str, dict] = {}

    for key in param_keys:
        buckets: dict = {}
        for r in results:
            val = str(r["params"][key])
            buckets.setdefault(val, []).append(r["score"])
        sensitivity[key] = {
            val: round(sum(scores) / len(scores), 4)
            for val, scores in sorted(buckets.items())
        }
    return sensitivity


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="us30_m5_200d.csv")
    ap.add_argument("--out",  default="backtest_optimization.json")
    args = ap.parse_args()

    # Build all combos
    keys   = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    combos = [dict(zip(keys, v)) for v in product(*values)]
    total  = len(combos)

    print(f"Loading data from {args.data} ...")
    base_cfg = SilverBulletConfig(**FIXED_PARAMS)
    df_raw   = load_csv(args.data)
    df_raw   = add_ny_time(df_raw)
    df       = add_window_id(df_raw, base_cfg)   # windows are fixed
    print(f"  {len(df):,} bars  "
          f"({df['timestamp_ny'].iloc[0].date()} to {df['timestamp_ny'].iloc[-1].date()})")
    print(f"\nRunning {total:,} combinations ...\n")

    results:  list[dict] = []
    skipped = 0
    t0 = time.perf_counter()

    for i, params in enumerate(combos, 1):
        result = _run_combo(params, df)
        if result is None:
            skipped += 1
        else:
            results.append(result)

        if i % 100 == 0 or i == total:
            elapsed = time.perf_counter() - t0
            eta     = (elapsed / i) * (total - i)
            pct     = i / total * 100
            print(f"  [{i:>5}/{total}]  {pct:5.1f}%  "
                  f"valid={len(results)}  skipped={skipped}  "
                  f"elapsed={elapsed:.0f}s  ETA={eta:.0f}s",
                  flush=True)

    elapsed = time.perf_counter() - t0
    print(f"\nDone in {elapsed:.1f}s.  "
          f"Valid configs: {len(results)} / {total}  (skipped {skipped})\n")

    if not results:
        print("No valid configurations found. Exiting.")
        sys.exit(1)

    results.sort(key=lambda r: r["score"], reverse=True)

    profitable = [r for r in results if (r["metrics"]["profit_factor"] or 0) > 1.0
                                        and r["metrics"]["net_pnl_usd"] > 0]

    print(f"Profitable configurations: {len(profitable)} / {len(results)}")
    print("\nTop 10 configs:\n")
    header = f"{'Rank':>4}  {'Net P&L':>9}  {'PF':>6}  {'WR%':>5}  {'AvgR':>6}  {'MaxDD':>8}  {'Trades':>6}  {'Score':>7}  Params"
    print(header)
    print("-" * len(header))
    for rank, r in enumerate(results[:10], 1):
        m = r["metrics"]
        pf = f"{m['profit_factor']:.2f}" if m["profit_factor"] is not None else " inf"
        p  = r["params"]
        param_str = (
            f"rr={p['rr']}  fvg={p['fvg_min_points']}  "
            f"entry={p['entry_in_fvg']}  minrisk={p['min_risk_points']}  "
            f"swing={p['swing_lookback']}  sweep={p['sweep_lookback']}  "
            f"buf={p['stop_buffer_points']}"
        )
        print(f"{rank:>4}  ${m['net_pnl_usd']:>8.0f}  {pf:>6}  "
              f"{m['win_rate_pct']:>4.1f}%  {m['avg_r']:>6.3f}  "
              f"${m['max_drawdown_usd']:>7.0f}  {m['num_trades']:>6}  "
              f"{r['score']:>7.4f}  {param_str}")

    sensitivity = _sensitivity(results)

    # ── Save JSON first so data is safe before any print can fail ────────────
    payload = {
        "meta": {
            "generated_at":      datetime.now(timezone.utc).isoformat(),
            "data_file":         args.data,
            "date_range":        {
                "start": str(df["timestamp_ny"].iloc[0].date()),
                "end":   str(df["timestamp_ny"].iloc[-1].date()),
            },
            "total_bars":        int(len(df)),
            "window_bars":       int(df["in_window"].sum()),
            "total_combos":      total,
            "valid_combos":      len(results),
            "profitable_combos": len(profitable),
            "min_trades_filter": MIN_TRADES,
            "fixed_params":      {k: v for k, v in FIXED_PARAMS.items()
                                  if k not in ("windows",)},
            "param_grid":        PARAM_GRID,
            "elapsed_seconds":   round(elapsed, 1),
        },
        "sensitivity":  sensitivity,
        "top_configs":  results[:20],
        "all_results":  results,
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)

    print(f"\nFull results saved to {args.out}")

    print("\nParameter sensitivity (mean score per value):")
    for param, vals in sensitivity.items():
        best_val = max(vals, key=lambda k: vals[k])
        print(f"  {param:<22}: {vals}  (best={best_val})")

    if profitable:
        best = profitable[0]
        print("\nBest profitable config:")
        print(json.dumps(best["params"], indent=2))
        print("Metrics:", json.dumps(best["metrics"], indent=2))


if __name__ == "__main__":
    main()
