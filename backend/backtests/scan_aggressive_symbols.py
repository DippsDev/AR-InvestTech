"""Scan liquid symbols for where Aggressive Silver Bullet holds up.

Volatility-scales US30 FVG/stop/min-risk by median M5 range (same method as
SB_TARGETS). Aggressive = extra windows + multiple trades per window.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
BASE_WINDOWS = [
    ("10:00", "11:00"),
    ("11:00", "12:00"),
    ("13:30", "14:30"),
]
UNIVERSE = {
    "US30m": "^DJI",
    "DE30m": "^GDAXI",
    "USTECm": "NQ=F",
    "US500m": "ES=F",
    "UK100m": "^FTSE",
    "JP225m": "^N225",
    "EURUSDm": "EURUSD=X",
    "GBPUSDm": "GBPUSD=X",
    "USDJPYm": "USDJPY=X",
    "AUDUSDm": "AUDUSD=X",
    "USDCHFm": "USDCHF=X",
    "USDCADm": "USDCAD=X",
    "EURJPYm": "EURJPY=X",
    "GBPJPYm": "GBPJPY=X",
    "XAUUSDm": "GC=F",
    "XAGUSDm": "SI=F",
}


def flatten_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    raw = raw.copy()
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [str(c[0]).lower() for c in raw.columns]
    else:
        raw.columns = [str(c).lower() for c in raw.columns]
    df = raw.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    time_col = next(c for c in df.columns if c in ("datetime", "date", "index"))
    df = df.rename(columns={time_col: "timestamp_utc"})
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    if "volume" not in df.columns:
        df["volume"] = 0
    return df[["timestamp_utc", "open", "high", "low", "close", "volume"]].dropna()


def overrides_from_df(df: pd.DataFrame) -> dict[str, float]:
    med = float((df["high"] - df["low"]).median())
    scale = med / US30_MEDIAN_RANGE if med > 0 else 1.0
    return dict(
        fvg_min_points=14.0 * scale,
        stop_buffer_points=0.5 * scale,
        min_risk_points=5.0 * scale,
    )


def cfg(symbol: str, windows, ov: dict, aggressive: bool) -> SilverBulletConfig:
    return SilverBulletConfig(
        symbol=symbol,
        windows=list(windows),
        one_trade_per_window=not aggressive,
        skip_news_days=True,
        **ov,
    )


def summarize(trades) -> dict:
    m = compute_metrics(trades)
    pf = m["profit_factor"]
    if pf in ("inf", float("inf")):
        pf = 99.0
    return {
        "n": m["num_trades"],
        "win": m["win_rate_pct"],
        "pf": float(pf) if not isinstance(pf, str) else 0.0,
        "net": m["net_pnl_usd"],
        "dd": m["max_drawdown_usd"],
        "r": m["avg_r"],
    }


def load_symbol(symbol: str, ticker: str) -> pd.DataFrame | None:
    local_us30 = ROOT / "data" / "us30_m5_200d.csv"
    if symbol == "US30m" and local_us30.exists():
        df = pd.read_csv(local_us30)
        df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
        return df[["timestamp_utc", "open", "high", "low", "close", "volume"]]
    try:
        raw = yf.download(ticker, interval="5m", period="60d", auto_adjust=False, progress=False)
    except Exception as exc:
        print(f"SKIP {symbol} download error: {exc}")
        return None
    if raw is None or raw.empty:
        print(f"SKIP {symbol} ({ticker}): no data")
        return None
    return flatten_ohlcv(raw)


def main() -> int:
    rows = []
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    print(f"{'symbol':<10} {'bars':>5} {'nA':>3} {'pfA':>5} {'nB':>3} {'pfB':>5} {'edge':>6} {'winA':>6} {'netA':>9}")
    print("-" * 72)
    for symbol, ticker in UNIVERSE.items():
        df = load_symbol(symbol, ticker)
        if df is None or len(df) < 400:
            if df is not None:
                print(f"SKIP {symbol}: only {len(df)} bars")
            continue
        path = data_dir / f"_scan_{symbol.lower()}.csv"
        df.to_csv(path, index=False)
        ov = overrides_from_df(df)
        a_cfg = cfg(symbol, AGG_WINDOWS, ov, True)
        b_cfg = cfg(symbol, BASE_WINDOWS, ov, False)
        a = summarize(run_backtest(prepare(str(path), a_cfg), a_cfg))
        b = summarize(run_backtest(prepare(str(path), b_cfg), b_cfg))
        edge = a["pf"] - b["pf"]
        print(
            f"{symbol:<10} {len(df):5d} {a['n']:3d} {a['pf']:5.2f} {b['n']:3d} {b['pf']:5.2f} "
            f"{edge:+6.2f} {a['win']:5.1f}% {a['net']:9.1f}"
        )
        rows.append({"symbol": symbol, **{f"a_{k}": v for k, v in a.items()}, **{f"b_{k}": v for k, v in b.items()}, "edge": edge, "bars": len(df)})

    hits = [
        r for r in rows
        if r["a_n"] >= 8 and r["a_pf"] >= 1.5 and r["a_r"] > 0 and r["edge"] >= 0
    ]
    print()
    print("Aggressive thrives (n>=8, PF>=1.5, avgR>0, PF >= baseline):")
    if not hits:
        print("  none in this sample")
    else:
        hits.sort(key=lambda r: (r["edge"], r["a_pf"]), reverse=True)
        for r in hits:
            print(
                f"  {r['symbol']:<10} agg PF {r['a_pf']:.2f} vs base {r['b_pf']:.2f} "
                f"(+{r['edge']:.2f})  trades {r['a_n']}  win {r['a_win']:.0f}%"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
