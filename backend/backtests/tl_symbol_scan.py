"""Scan every stored symbol for Trendline, at the live config.

Ranks instruments on full *_m5_max.csv history. The 180-day window is the
same run's trades whose entry falls in the last 180 calendar days — not a
fresh backtest on a truncated frame, which would rebuild trendlines without
the prior swings they actually depend on.

Each symbol is run at 1x and 3x touch/obstruction tolerance — the two
settings the live book uses (USDJPYm at 1x, DE30m/USTECm at 3x).

Usage: python backtests/tl_symbol_scan.py
"""
from __future__ import annotations

import json
import os
import sys
from glob import glob

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.logger import logger
from silver_bullet.metrics import compute_metrics
from trendline.backtest import BacktestCosts, run_backtest
from trendline.config import TrendlineConfig
from trendline.data import prepare_from_m5

logger.setLevel("ERROR")

US30_MEDIAN_M5_RANGE = 24.9
RECENT_DAYS = 180
OUT = os.path.join(os.path.dirname(__file__), "tl_symbol_scan.json")

FILE_TO_SYMBOL = {
    "us30": "US30m",
}


def symbol_name(short: str) -> str:
    if short in FILE_TO_SYMBOL:
        return FILE_TO_SYMBOL[short]
    if short.endswith("m"):
        return short[:-1].upper() + "m"
    return short.upper() + "m"


def scaled_cfg(scale: float, touch_mult: float, symbol: str) -> TrendlineConfig:
    return TrendlineConfig(
        symbol=symbol,
        obstruction_tolerance_points=3.0 * touch_mult * scale,
        touch_tolerance_points=3.0 * touch_mult * scale,
        breach_tolerance_points=5.0 * scale,
        stop_buffer_points=5.0 * scale,
        min_risk_points=15.0 * scale,
        skip_news_days=True,
    )


def costs_for(scale: float) -> BacktestCosts:
    return BacktestCosts(
        spread_points=2.0 * scale,
        slippage_points=1.0 * scale,
        commission_per_trade=5.0,
        risk_per_trade=100.0,
        point_value=1.0,
    )


def pack(m: dict) -> dict:
    pf = m["profit_factor"]
    return {
        "num_trades": m["num_trades"],
        "net_pnl_usd": m["net_pnl_usd"],
        "win_rate_pct": m["win_rate_pct"],
        "avg_r": m["avg_r"],
        "profit_factor": pf if isinstance(pf, (int, float)) else None,
        "max_drawdown_usd": m["max_drawdown_usd"],
        "expectancy_usd": m["expectancy_usd"],
    }


def fmt(m: dict, symbol: str, touch_mult: float, scale: float, label: str) -> str:
    pf = m["profit_factor"]
    pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else "n/a"
    return (
        f"{symbol:<9} {touch_mult:>3.0f}x {scale:>8.4f} {label:<6} "
        f"{m['num_trades']:>6} {m['win_rate_pct']:>5.1f}% "
        f"{m['net_pnl_usd']:>10.2f} {pf_s:>6} "
        f"{m['max_drawdown_usd']:>9.2f} {m['expectancy_usd']:>8.2f}"
    )


def main() -> int:
    files = sorted(glob("data/*_m5_max.csv"))
    if not files:
        print("no data/*_m5_max.csv files found", file=sys.stderr)
        return 1

    rows = []
    header = (
        f"{'Symbol':<9} {'Mult':>4} {'Scale':>8} {'Window':<6} "
        f"{'Trades':>6} {'Win%':>6} {'Net P&L':>10} {'PF':>6} {'MaxDD':>9} {'Exp':>8}"
    )
    print(header)
    print("-" * len(header))

    for path in files:
        short = os.path.basename(path).replace("_m5_max.csv", "")
        symbol = symbol_name(short)
        m5 = pd.read_csv(path)
        scale = float((m5["high"] - m5["low"]).median()) / US30_MEDIAN_M5_RANGE
        df = prepare_from_m5(path)
        cutoff = df["timestamp_ny"].iloc[-1] - pd.Timedelta(days=RECENT_DAYS)

        for touch_mult in (1.0, 3.0):
            cfg = scaled_cfg(scale, touch_mult, symbol)
            trades = run_backtest(df, cfg, costs_for(scale))
            recent = [t for t in trades if t.entry_time is not None and t.entry_time >= cutoff]
            full_m = compute_metrics(trades)
            rec_m = compute_metrics(recent)
            entry = {
                "symbol": symbol,
                "file": short,
                "scale": round(scale, 8),
                "touch_mult": touch_mult,
                "start": str(df["timestamp_ny"].iloc[0].date()),
                "end": str(df["timestamp_ny"].iloc[-1].date()),
                "h1_bars": int(len(df)),
                "full": pack(full_m),
                "180d": pack(rec_m),
            }
            rows.append(entry)
            print(fmt(full_m, symbol, touch_mult, scale, "full"))
            print(fmt(rec_m, symbol, touch_mult, scale, "180d"))
            sys.stdout.flush()
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(
                    {"us30_median_m5_range": US30_MEDIAN_M5_RANGE, "rows": rows},
                    fh,
                    indent=2,
                )

    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
