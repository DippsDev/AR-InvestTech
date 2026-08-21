"""Aggressive Silver Bullet backtest on the live SB symbols.

Uses Yahoo 5-minute history (max ~60 days) as a stand-in for broker CFDs.
The symbol list follows SB_TARGETS so a retarget does not need a second edit.

Aggressive live wiring (bot.py): extra windows + one_trade_per_window=False.
Per-symbol FVG / stop / min-risk from SB_TARGETS overwrite the 3.0 / 2.0
Aggressive floors, so this matches that order of operations.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from multi_symbol_targets import SB_TARGETS
from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare
from silver_bullet.backtest import run_backtest
from silver_bullet.metrics import compute_metrics

logging.disable(logging.CRITICAL)

US30_MEDIAN_RANGE = 24.9
AGG_WINDOWS = [
    ("03:00", "04:00"),
    ("04:00", "05:00"),
    ("10:00", "11:00"),
    ("11:00", "12:00"),
    ("13:30", "14:30"),
]
YAHOO = {
    "DE30m": "^GDAXI",
    "USTECm": "NQ=F",
    "XAUUSDm": "GC=F",
    "EURUSDm": "EURUSD=X",
    "GBPUSDm": "GBPUSD=X",
}


def _flatten_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw = raw.copy()
        raw.columns = [str(c).lower() for c in raw.columns]
    df = raw.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    time_col = next(c for c in df.columns if c in ("datetime", "date", "index"))
    df = df.rename(columns={time_col: "timestamp_utc"})
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    if "volume" not in df.columns:
        df["volume"] = 0
    return df[["timestamp_utc", "open", "high", "low", "close", "volume"]].dropna()


def download(symbol: str) -> pd.DataFrame:
    ticker = YAHOO[symbol]
    raw = yf.download(ticker, interval="5m", period="60d", auto_adjust=False, progress=False)
    if raw is None or raw.empty:
        raise RuntimeError(f"No Yahoo data for {ticker}")
    return _flatten_ohlcv(raw)


def gold_overrides(df: pd.DataFrame) -> dict[str, float]:
    med = float((df["high"] - df["low"]).median())
    scale = med / US30_MEDIAN_RANGE
    return dict(
        fvg_min_points=14.0 * scale,
        stop_buffer_points=0.5 * scale,
        min_risk_points=5.0 * scale,
    )


def aggressive_cfg(symbol: str, overrides: dict) -> SilverBulletConfig:
    return SilverBulletConfig(
        symbol=symbol,
        windows=list(AGG_WINDOWS),
        one_trade_per_window=False,
        skip_news_days=True,
        **overrides,
    )


def main() -> int:
    out_dir = ROOT / "data"
    out_dir.mkdir(exist_ok=True)
    print("Aggressive SB on live symbols | Yahoo M5 ~60d")
    print(f"Windows: {AGG_WINDOWS}")
    print(f"one_trade_per_window=False  skip_news_days=True")
    print()
    print(f"{'symbol':<10} {'bars':>6} {'n':>4} {'win%':>6} {'PF':>6} {'net$':>10} {'maxDD':>10} {'avgR':>7}")
    print("-" * 72)

    combined = []
    for symbol, overrides in SB_TARGETS.items():
        df = download(symbol)
        csv_path = out_dir / f"{symbol.lower()}_m5_yahoo.csv"
        df.to_csv(csv_path, index=False)
        overrides = dict(overrides) if overrides else gold_overrides(df)
        cfg = aggressive_cfg(symbol, overrides)
        prepared = prepare(str(csv_path), cfg)
        trades = run_backtest(prepared, cfg)
        m = compute_metrics(trades)
        pf = m["profit_factor"]
        pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else str(pf)
        print(
            f"{symbol:<10} {len(prepared):6d} {m['num_trades']:4d} "
            f"{m['win_rate_pct']:5.1f}% {pf_s:>6} {m['net_pnl_usd']:10.2f} "
            f"{m['max_drawdown_usd']:10.2f} {m['avg_r']:7.3f}"
        )
        print(
            f"           fvg={cfg.fvg_min_points:.6g}  min_risk={cfg.min_risk_points:.6g}  "
            f"stop_buf={cfg.stop_buffer_points:.6g}  "
            f"{prepared['timestamp_ny'].iloc[0].date()} -> {prepared['timestamp_ny'].iloc[-1].date()}"
        )
        combined.extend(trades)

    print("-" * 72)
    all_m = compute_metrics(combined)
    pf = all_m["profit_factor"]
    pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else str(pf)
    print(
        f"{'ALL SB':<10} {'':6} {all_m['num_trades']:4d} "
        f"{all_m['win_rate_pct']:5.1f}% {pf_s:>6} {all_m['net_pnl_usd']:10.2f} "
        f"{all_m['max_drawdown_usd']:10.2f} {all_m['avg_r']:7.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
