"""Load OHLCV data for the Mutanabby backtester.

The indicator declares no timeframe — SuperTrend + SMA work on whatever chart
they are dropped onto — so unlike trendline/data.py (which must resample to H1)
this loads the stored M5 history natively. `timeframe` is offered anyway so the
same logic can be compared across M5/M15/H1/H4 from one CSV, since which
timeframe this edge lives on is an open question rather than a given.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from silver_bullet.news_calendar import HIGH_IMPACT_DATES

NY_TZ = ZoneInfo("America/New_York")


def load_m5_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp_utc"])
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    return df


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Aggregate M5 OHLC up to `rule` bars, dropping empty periods (weekends/gaps)."""
    df = df.set_index("timestamp_utc")
    out = df.resample(rule, label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    })
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out.reset_index()


def prepare(path: str | Path, timeframe: Optional[str] = None) -> pd.DataFrame:
    """Full pipeline: load M5 -> optional resample -> NY time -> news flag.

    `timeframe` is a pandas offset alias ("15min", "1h", "4h"); None keeps the
    native M5 bars.
    """
    df = load_m5_csv(path)
    if timeframe:
        df = resample(df, timeframe)
    df["timestamp_ny"] = df["timestamp_utc"].dt.tz_convert(NY_TZ)
    df["date_str"] = df["timestamp_ny"].dt.date.astype(str)
    df["is_news_day"] = df["date_str"].isin(HIGH_IMPACT_DATES)
    return df
