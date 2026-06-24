"""
Download historical M5 OHLCV bars from MT5 and save as CSV.

Usage:
    python fetch_mt5_data.py [--symbol US30] [--years 3] [--out us30_m5_3y.csv]

The CSV produced is directly compatible with silver_bullet run_backtest --data.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()


def _connect() -> None:
    import MetaTrader5 as mt5

    login    = int(os.environ["MT5_LOGIN"])
    password = os.environ["MT5_PASSWORD"]
    server   = os.environ["MT5_SERVER"]

    if not mt5.initialize(login=login, password=password, server=server):
        print(f"MT5 initialize failed: {mt5.last_error()}")
        sys.exit(1)
    print(f"Connected to {server} as {login}")


def fetch(symbol: str, years: int) -> pd.DataFrame:
    import MetaTrader5 as mt5

    utc_to   = datetime.now(timezone.utc)
    utc_from = utc_to - timedelta(days=365 * years)

    print(f"Fetching {symbol} M5  {utc_from.date()} to {utc_to.date()} ...")

    if not mt5.symbol_info(symbol):
        mt5.symbol_select(symbol, True)

    rates = mt5.copy_rates_range(
        symbol,
        mt5.TIMEFRAME_M5,
        utc_from,
        utc_to,
    )

    if rates is None or len(rates) == 0:
        print(f"No data returned: {mt5.last_error()}")
        sys.exit(1)

    df = pd.DataFrame(rates)
    df["timestamp_utc"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={
        "open":      "open",
        "high":      "high",
        "low":       "low",
        "close":     "close",
        "tick_volume": "volume",
    })
    df = df[["timestamp_utc", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    return df


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch MT5 M5 data to CSV")
    p.add_argument("--symbol", default="US30",  help="MT5 symbol name")
    p.add_argument("--years",  type=int, default=3, help="Years of history to download")
    p.add_argument("--out",    default=None, help="Output CSV path (default: <symbol>_m5_<N>y.csv)")
    args = p.parse_args()

    out_path = args.out or f"{args.symbol.lower()}_m5_{args.years}y.csv"

    _connect()
    df = fetch(args.symbol, args.years)

    print(f"  {len(df):,} bars  ({df['timestamp_utc'].iloc[0].date()} to {df['timestamp_utc'].iloc[-1].date()})")
    df.to_csv(out_path, index=False)
    print(f"Saved to {out_path}")

    import MetaTrader5 as mt5
    mt5.shutdown()


if __name__ == "__main__":
    main()
