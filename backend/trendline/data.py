"""Load OHLCV data for the Trendline backtester.

Trendline trades H1 candles, but the only stored US30 history in this repo
is M5 (see backend/data/*.csv, built for Silver Bullet's backtester). Rather
than requiring a separate native-H1 export, `prepare_from_m5` resamples M5
up to H1 — a reasonable approximation for gauging the strategy's edge, not
byte-identical to broker-native H1 candles (which are built from the
broker's own tick stream, not from its own M5 bars).
"""
from __future__ import annotations

from pathlib import Path
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


def resample_to_h1(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate M5 OHLC up to H1 bars, dropping empty hours (weekends/gaps)."""
    df = df.set_index("timestamp_utc")
    h1 = df.resample("1h", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last",
    })
    h1 = h1.dropna(subset=["open", "high", "low", "close"])
    h1 = h1.reset_index()
    return h1


def prepare_from_m5(path: str | Path) -> pd.DataFrame:
    """Full pipeline: load M5 -> resample to H1 -> NY time -> news flag."""
    df = load_m5_csv(path)
    df = resample_to_h1(df)
    df["timestamp_ny"] = df["timestamp_utc"].dt.tz_convert(NY_TZ)
    df["date_str"] = df["timestamp_ny"].dt.date.astype(str)
    df["is_news_day"] = df["date_str"].isin(HIGH_IMPACT_DATES)
    return df
