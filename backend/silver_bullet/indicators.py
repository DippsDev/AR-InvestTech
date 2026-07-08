"""
Pure indicator functions — no side-effects, no look-ahead.

Lookahead-safety rule
---------------------
A swing at bar j with lookback L is only "confirmed" (visible to the
strategy) at bar j + L.  Every function here accepts a `current_bar`
parameter and internally limits the scan to swings confirmed at
current_bar - 1 or earlier, i.e. whose right-side bars have ALL closed.

All array arguments are assumed to be the FULL history up to (and
including) current_bar.  Never pass future data.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Swing-point detection
# ---------------------------------------------------------------------------

def is_swing_high(highs: np.ndarray, idx: int, lookback: int) -> bool:
    """True if highs[idx] > every bar in [idx-lookback, idx-1] ∪ [idx+1, idx+lookback].

    Returns False if there is insufficient data on either side.
    """
    n = len(highs)
    if idx < lookback or idx + lookback >= n:
        return False
    center = highs[idx]
    return bool(
        np.all(center > highs[idx - lookback: idx])
        and np.all(center > highs[idx + 1: idx + lookback + 1])
    )


def is_swing_low(lows: np.ndarray, idx: int, lookback: int) -> bool:
    """True if lows[idx] < every bar in [idx-lookback, idx-1] ∪ [idx+1, idx+lookback]."""
    n = len(lows)
    if idx < lookback or idx + lookback >= n:
        return False
    center = lows[idx]
    return bool(
        np.all(center < lows[idx - lookback: idx])
        and np.all(center < lows[idx + 1: idx + lookback + 1])
    )


def get_swing_highs(
    highs: np.ndarray, lookback: int
) -> List[Tuple[int, float]]:
    """Return [(bar_index, price)] for every confirmed swing high in the array."""
    n = len(highs)
    return [
        (i, float(highs[i]))
        for i in range(lookback, n - lookback)
        if is_swing_high(highs, i, lookback)
    ]


def get_swing_lows(
    lows: np.ndarray, lookback: int
) -> List[Tuple[int, float]]:
    """Return [(bar_index, price)] for every confirmed swing low in the array."""
    n = len(lows)
    return [
        (i, float(lows[i]))
        for i in range(lookback, n - lookback)
        if is_swing_low(lows, i, lookback)
    ]


# ---------------------------------------------------------------------------
# Sweep detection  (no look-ahead guaranteed by max_confirmed_idx)
# ---------------------------------------------------------------------------

def detect_sellside_sweep(
    lows: np.ndarray,
    closes: np.ndarray,
    current_bar: int,
    swing_lookback: int,
    sweep_lookback: int,
) -> Optional[float]:
    """Detect whether the bar at current_bar sweeps a prior confirmed swing low.

    A sellside sweep:
      - current bar's low < swing_low_level, AND
      - current bar's close > swing_low_level  (wick raid, not breakout).

    Only swing lows confirmed at or before current_bar-1 are eligible,
    i.e., the swing low at bar j is used only if j + swing_lookback < current_bar.

    Returns the swept level (price) or None.
    If multiple lows were swept, returns the most recently formed one.
    """
    # Latest bar that could be a confirmed swing low
    max_j = current_bar - swing_lookback - 1
    if max_j < swing_lookback:
        return None

    min_j = max(swing_lookback, current_bar - sweep_lookback - swing_lookback)

    bar_low = lows[current_bar]
    bar_close = closes[current_bar]

    # Scan from most-recent to oldest so we return the nearest swept level
    for j in range(max_j, min_j - 1, -1):
        if is_swing_low(lows, j, swing_lookback):
            level = float(lows[j])
            if bar_low < level and bar_close > level:
                return level

    return None


def detect_buyside_sweep(
    highs: np.ndarray,
    closes: np.ndarray,
    current_bar: int,
    swing_lookback: int,
    sweep_lookback: int,
) -> Optional[float]:
    """Detect whether the bar at current_bar sweeps a prior confirmed swing high.

    A buyside sweep:
      - current bar's high > swing_high_level, AND
      - current bar's close < swing_high_level.

    Returns the swept level or None.
    """
    max_j = current_bar - swing_lookback - 1
    if max_j < swing_lookback:
        return None

    min_j = max(swing_lookback, current_bar - sweep_lookback - swing_lookback)

    bar_high = highs[current_bar]
    bar_close = closes[current_bar]

    for j in range(max_j, min_j - 1, -1):
        if is_swing_high(highs, j, swing_lookback):
            level = float(highs[j])
            if bar_high > level and bar_close < level:
                return level

    return None


# ---------------------------------------------------------------------------
# Fair Value Gap detection  (3-candle imbalance, no look-ahead)
# ---------------------------------------------------------------------------

def detect_bullish_fvg(
    highs: np.ndarray,
    lows: np.ndarray,
    idx: int,
    fvg_min_points: float,
) -> Optional[Tuple[float, float]]:
    """Check whether candles [idx-2, idx-1, idx] form a bullish FVG.

    Condition : lows[idx] > highs[idx-2]
    Zone      : (highs[idx-2], lows[idx])   →  (bottom, top)

    Returns (bottom, top) or None.
    """
    if idx < 2:
        return None
    bottom = float(highs[idx - 2])
    top = float(lows[idx])
    if top > bottom and (top - bottom) >= fvg_min_points:
        return (bottom, top)
    return None


def detect_bearish_fvg(
    highs: np.ndarray,
    lows: np.ndarray,
    idx: int,
    fvg_min_points: float,
) -> Optional[Tuple[float, float]]:
    """Check whether candles [idx-2, idx-1, idx] form a bearish FVG.

    Condition : highs[idx] < lows[idx-2]
    Zone      : (highs[idx], lows[idx-2])   →  (bottom, top)

    Returns (bottom, top) or None.
    """
    if idx < 2:
        return None
    bottom = float(highs[idx])
    top = float(lows[idx - 2])
    if top > bottom and (top - bottom) >= fvg_min_points:
        return (bottom, top)
    return None


# ---------------------------------------------------------------------------
# Entry price within the FVG
# ---------------------------------------------------------------------------

def fvg_entry_price(
    fvg_bottom: float,
    fvg_top: float,
    direction: str,
    entry_in_fvg: str,
) -> float:
    """Compute the limit-order entry price inside the FVG zone.

    Bullish (price retracing down into gap):
      near_edge → top of gap (lows[idx])   — first edge hit on the way down
      far_edge  → bottom of gap (highs[idx-2])
    Bearish (price rallying up into gap):
      near_edge → bottom of gap (highs[idx])  — first edge hit on the way up
      far_edge  → top of gap (lows[idx-2])
    """
    if direction == "bullish":
        near, far = fvg_top, fvg_bottom
    elif direction == "bearish":
        near, far = fvg_bottom, fvg_top
    else:
        raise ValueError(f"Unknown direction: {direction!r}")

    if entry_in_fvg == "near_edge":
        return near
    if entry_in_fvg == "far_edge":
        return far
    if entry_in_fvg == "mid":
        return (near + far) / 2.0
    raise ValueError(f"Unknown entry_in_fvg: {entry_in_fvg!r}")


# ---------------------------------------------------------------------------
# Nearest liquidity pools  (used for opposite_liquidity target mode)
# ---------------------------------------------------------------------------

def nearest_buyside_liquidity(
    highs: np.ndarray,
    current_bar: int,
    swing_lookback: int,
    above_price: float,
) -> Optional[float]:
    """Return the nearest confirmed swing high above `above_price`.

    Only considers swings confirmed at or before current_bar (i.e., all right-
    side bars have closed).
    """
    candidates = get_swing_highs(highs[: current_bar - swing_lookback], swing_lookback)
    above = [lvl for _, lvl in candidates if lvl > above_price]
    return min(above) if above else None


def nearest_sellside_liquidity(
    lows: np.ndarray,
    current_bar: int,
    swing_lookback: int,
    below_price: float,
) -> Optional[float]:
    """Return the nearest confirmed swing low below `below_price`."""
    candidates = get_swing_lows(lows[: current_bar - swing_lookback], swing_lookback)
    below = [lvl for _, lvl in candidates if lvl < below_price]
    return max(below) if below else None
