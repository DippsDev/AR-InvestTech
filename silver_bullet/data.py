"""Load, validate, and annotate OHLCV data with NY-timezone window flags."""
from __future__ import annotations

from datetime import time
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

from .config import SilverBulletConfig
from .news_calendar import HIGH_IMPACT_DATES

NY_TZ = ZoneInfo("America/New_York")
UTC_TZ = ZoneInfo("UTC")

_REQUIRED_COLS = {"timestamp_utc", "open", "high", "low", "close", "volume"}


def load_csv(path: str | Path) -> pd.DataFrame:
    """Read OHLCV CSV; return a UTC-indexed, sorted DataFrame."""
    df = pd.read_csv(path, parse_dates=["timestamp_utc"])
    missing = _REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="raise")
    return df


def _parse_hhmm(t: str) -> time:
    h, m = t.strip().split(":")
    return time(int(h), int(m))


def add_ny_time(df: pd.DataFrame) -> pd.DataFrame:
    """Append a 'timestamp_ny' column (America/New_York, DST-aware)."""
    df = df.copy()
    df["timestamp_ny"] = df["timestamp_utc"].dt.tz_convert(NY_TZ)
    return df


def add_window_id(df: pd.DataFrame, cfg: SilverBulletConfig) -> pd.DataFrame:
    """
    Append 'window_id' (1-based integer matching cfg.windows index, or pd.NA)
    and 'in_window' (bool).

    A candle's bar-open timestamp determines which window it belongs to so that
    window boundaries are checked on already-closed bars — no lookahead.
    """
    df = df.copy()
    df["window_id"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["in_window"] = False

    parsed = [(_parse_hhmm(s), _parse_hhmm(e)) for s, e in cfg.windows]
    ny_time = df["timestamp_ny"].dt.time

    for idx, (start, end) in enumerate(parsed, start=1):
        if end > start:
            mask = (ny_time >= start) & (ny_time < end)
        else:
            mask = (ny_time >= start) | (ny_time < end)
        df.loc[mask, "window_id"] = idx
        df.loc[mask, "in_window"] = True

    return df


def add_prev_day_bias(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'prev_day_bias' column:
      +1 = previous trading day was bullish (close > open) — only take longs today
      -1 = previous trading day was bearish (close < open) — only take shorts today
       0 = first day in dataset or flat day (no filter applied)

    Using the prior day's completed candle direction, not an intraday reference,
    so there is zero lookahead: when we enter a trade today the previous candle
    is always fully closed.
    """
    df = df.copy()
    ny_date = df["timestamp_ny"].dt.date

    daily_open_px  = df.groupby(ny_date)["open"].first()
    daily_close_px = df.groupby(ny_date)["close"].last()

    dates = daily_open_px.index.tolist()
    bias_map = {
        d: (1 if daily_close_px[d] > daily_open_px[d] else
            -1 if daily_close_px[d] < daily_open_px[d] else 0)
        for d in dates
    }
    bias_series  = pd.Series(bias_map, dtype=int)
    prev_bias    = bias_series.shift(1, fill_value=0)
    df["prev_day_bias"] = ny_date.map(prev_bias).fillna(0).astype(int)
    return df


def add_news_flag(df: pd.DataFrame) -> pd.DataFrame:
    """Add 'is_news_day' bool column using the HIGH_IMPACT_DATES calendar."""
    df = df.copy()
    ny_date_str = df["timestamp_ny"].dt.date.astype(str)
    df["is_news_day"] = ny_date_str.isin(HIGH_IMPACT_DATES)
    return df


def prepare(
    path: str | Path,
    cfg: SilverBulletConfig,
    m1_path: Optional[str | Path] = None,
) -> pd.DataFrame:
    """Full pipeline: load → NY time → window flags → daily open → news flag.

    m1_path is accepted for future M1 entry-refinement but unused in this phase.
    """
    df = load_csv(path)
    df = add_ny_time(df)
    df = add_window_id(df, cfg)
    df = add_prev_day_bias(df)
    df = add_news_flag(df)
    return df
