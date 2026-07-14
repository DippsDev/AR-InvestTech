"""
Pure indicator functions — no side-effects, no look-ahead.

Swing-point detection and "nearest opposing swing" lookups are reused
verbatim from silver_bullet.indicators (they are generic, not ICT-specific).
This module adds the trendline-specific logic: constructing a line from two
confirmed swing points, checking whether a bar has breached or touched it.

Lookahead-safety rule
----------------------
A swing at bar j with lookback L is only "confirmed" at bar j + L (all of its
right-side bars have closed). get_swing_highs/get_swing_lows already enforce
this for whatever slice of the array they are given, so passing
`highs[:current_bar + 1]` / `lows[:current_bar + 1]` keeps every trendline
built here look-ahead safe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

# Reused verbatim from silver_bullet — NOT reimplemented, NOT modified.
from silver_bullet.indicators import (  # noqa: F401  (re-exported for convenience)
    get_swing_highs,
    get_swing_lows,
    nearest_buyside_liquidity,
    nearest_sellside_liquidity,
)


@dataclass
class TrendLine:
    """A trendline drawn between two confirmed swing points of the same kind."""
    kind: str              # "support" | "resistance"
    anchor1_bar: int
    anchor1_price: float
    anchor2_bar: int
    anchor2_price: float
    slope: float            # price change per bar index
    broken: bool = False
    broken_bar: Optional[int] = None


def value_at(line: TrendLine, bar_idx: int) -> float:
    """Interpolated/extrapolated price of the line at bar_idx."""
    return line.anchor1_price + line.slope * (bar_idx - line.anchor1_bar)


def is_same_line(existing: Optional[TrendLine], candidate: Optional[TrendLine]) -> bool:
    """True if `candidate` is anchored on the same two swing points as `existing`.

    Used to avoid discarding an already-tracked line's broken/broken_bar state
    every bar just because the construction routine recomputed an identical
    pair of anchors.
    """
    if existing is None or candidate is None:
        return False
    return (
        existing.kind == candidate.kind
        and existing.anchor1_bar == candidate.anchor1_bar
        and existing.anchor2_bar == candidate.anchor2_bar
    )


def _avg_range(highs: np.ndarray, lows: np.ndarray, idx: int, lookback: int) -> float:
    start = max(0, idx - lookback)
    if start >= idx:
        return 1e-9
    seg = highs[start:idx] - lows[start:idx]
    return float(np.mean(seg)) if len(seg) else 1e-9


def _steepness_ok(price1: float, bar1: int, price2: float, bar2: int,
                   avg_range: float, max_ratio: float) -> bool:
    if bar2 <= bar1:
        return False
    slope_per_bar = abs(price2 - price1) / (bar2 - bar1)
    return slope_per_bar <= max_ratio * max(avg_range, 1e-9)


def _obstructed_support(lows: np.ndarray, i1: int, v1: float, i2: int, v2: float,
                         tol: float) -> bool:
    for j in range(i1 + 1, i2):
        line_val = v1 + (v2 - v1) * (j - i1) / (i2 - i1)
        if lows[j] < line_val - tol:
            return True
    return False


def _obstructed_resistance(highs: np.ndarray, i1: int, v1: float, i2: int, v2: float,
                            tol: float) -> bool:
    for j in range(i1 + 1, i2):
        line_val = v1 + (v2 - v1) * (j - i1) / (i2 - i1)
        if highs[j] > line_val + tol:
            return True
    return False


def build_support_line(
    lows: np.ndarray,
    highs: np.ndarray,
    current_bar: int,
    swing_lookback: int,
    avg_range_lookback: int,
    steepness_max_ratio: float,
    obstruction_tolerance_points: float,
) -> Optional[TrendLine]:
    """Connect the 2 most recent CONFIRMED swing lows visible at current_bar.

    Rejects the pair if any bar strictly between the two anchors undercuts
    the interpolated line ("drawn through an obstruction"), or if the slope
    is too steep relative to recent volatility ("steep trendlines are
    unreliable").
    """
    candidates = get_swing_lows(lows[: current_bar + 1], swing_lookback)
    if len(candidates) < 2:
        return None
    (i1, v1), (i2, v2) = candidates[-2], candidates[-1]
    if _obstructed_support(lows, i1, v1, i2, v2, obstruction_tolerance_points):
        return None
    avg_range = _avg_range(highs, lows, current_bar, avg_range_lookback)
    if not _steepness_ok(v1, i1, v2, i2, avg_range, steepness_max_ratio):
        return None
    slope = (v2 - v1) / (i2 - i1)
    return TrendLine("support", i1, v1, i2, v2, slope)


def build_resistance_line(
    lows: np.ndarray,
    highs: np.ndarray,
    current_bar: int,
    swing_lookback: int,
    avg_range_lookback: int,
    steepness_max_ratio: float,
    obstruction_tolerance_points: float,
) -> Optional[TrendLine]:
    """Symmetric to build_support_line: connects the 2 most recent confirmed
    swing highs, rejecting on obstruction (overcut) or excessive steepness."""
    candidates = get_swing_highs(highs[: current_bar + 1], swing_lookback)
    if len(candidates) < 2:
        return None
    (i1, v1), (i2, v2) = candidates[-2], candidates[-1]
    if _obstructed_resistance(highs, i1, v1, i2, v2, obstruction_tolerance_points):
        return None
    avg_range = _avg_range(highs, lows, current_bar, avg_range_lookback)
    if not _steepness_ok(v1, i1, v2, i2, avg_range, steepness_max_ratio):
        return None
    slope = (v2 - v1) / (i2 - i1)
    return TrendLine("resistance", i1, v1, i2, v2, slope)


def check_breach(line: TrendLine, bar_idx: int, close: float, tolerance: float) -> bool:
    """True if `close` at bar_idx closes beyond the line by more than tolerance."""
    val = value_at(line, bar_idx)
    if line.kind == "support":
        return close < val - tolerance
    return close > val + tolerance


def check_touch(line: TrendLine, bar_idx: int, high: float, low: float,
                 tolerance: float) -> bool:
    """True if the bar's range comes within `tolerance` of the line's value
    — either just above it, or piercing slightly below/above it — for a
    support line via its low, a resistance line via its high.

    Bounded on both sides deliberately: a bar whose low sits far below a
    support line (e.g. a breakout that happened several bars ago) must NOT
    keep matching as a "touch" on every subsequent bar just because it's
    still below the line.
    """
    val = value_at(line, bar_idx)
    if line.kind == "support":
        return val - tolerance <= low <= val + tolerance
    return val - tolerance <= high <= val + tolerance
