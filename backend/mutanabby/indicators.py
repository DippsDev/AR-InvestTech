"""
Pine Script v5 function ports — no side-effects, no look-ahead.

Every function here is a deliberate, line-by-line translation of the built-in
it is named after, because parity with the chart is the whole point: if the
backtest disagrees with what the user saw on TradingView, the backtest is
wrong. Where Pine's behaviour is surprising, the surprise is reproduced and
commented rather than "fixed".

Look-ahead safety
-----------------
Every series below is causal: value[i] depends only on inputs at indices <= i.
That is what lets strategy.py compute all of them once over the full array and
then read them bar-by-bar, instead of recomputing an O(n) SuperTrend at every
bar for O(n^2) total. Do not add a centred/backward-filled series to this
module without revisiting that assumption.

NaN convention
--------------
Pine's `na` becomes np.nan. This maps cleanly onto Pine's comparison semantics:
in Pine a comparison involving `na` yields `na`, and a `na` condition takes the
false branch of a ternary — which is exactly what Python/NumPy do with nan
(`nan > 0` is False, and so is `nan < 0`). Ports below rely on this.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def nz(value: float, replacement: float = 0.0) -> float:
    """Pine `nz()` — substitute for na."""
    return replacement if (value is None or np.isnan(value)) else value


def sma(values: np.ndarray, length: int) -> np.ndarray:
    """Pine `ta.sma` — simple moving average, na until `length` bars exist."""
    if length <= 0:
        raise ValueError("length must be positive")
    return pd.Series(values, dtype=float).rolling(length).mean().to_numpy()


def rma(values: np.ndarray, length: int) -> np.ndarray:
    """Pine `ta.rma` — Wilder smoothing (alpha = 1/length).

    Seeded with the SMA of the first `length` values, matching Pine's
    `na(sum[1]) ? ta.sma(src, length) : alpha*src + (1-alpha)*sum[1]`.
    Leading NaNs in `values` are skipped before seeding, so callers can pass a
    `ta.change`-style series whose first element is na (as RSI does).
    """
    if length <= 0:
        raise ValueError("length must be positive")
    values = np.asarray(values, dtype=float)
    n = len(values)
    out = np.full(n, np.nan)

    start = 0
    while start < n and np.isnan(values[start]):
        start += 1
    seed_idx = start + length - 1
    if seed_idx >= n:
        return out

    alpha = 1.0 / length
    out[seed_idx] = float(np.mean(values[start:seed_idx + 1]))
    for i in range(seed_idx + 1, n):
        out[i] = alpha * values[i] + (1.0 - alpha) * out[i - 1]
    return out


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    """Pine `ta.tr(true)` — the `true` argument makes bar 0 fall back to
    high-low instead of na, since there is no previous close to compare."""
    n = len(high)
    tr = np.empty(n, dtype=float)
    if n == 0:
        return tr
    tr[0] = high[0] - low[0]
    if n > 1:
        prev_close = close[:-1]
        tr[1:] = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
        )
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int) -> np.ndarray:
    """Pine `ta.atr` — rma(tr, length)."""
    return rma(true_range(high, low, close), length)


def rsi(values: np.ndarray, length: int) -> np.ndarray:
    """Pine's RSI, spelled out the long way exactly as the indicator does:

        up   = ta.rma(math.max(ta.change(src), 0), len)
        down = ta.rma(-math.min(ta.change(src), 0), len)
        rsi  = down == 0 ? 100 : up == 0 ? 0 : 100 - 100 / (1 + up/down)

    Diagnostic only — in the source this drives bar colouring and has no
    influence on any signal.
    """
    values = np.asarray(values, dtype=float)
    change = np.full(len(values), np.nan)
    change[1:] = np.diff(values)

    up = rma(np.maximum(change, 0.0), length)
    down = rma(-np.minimum(change, 0.0), length)

    out = np.full(len(values), np.nan)
    valid = ~(np.isnan(up) | np.isnan(down))
    # Order matters: Pine tests `down == 0` first, so a flat series reads 100.
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.where(down != 0, up / down, np.nan)
        computed = 100.0 - 100.0 / (1.0 + rs)
    out[valid] = computed[valid]
    out[valid & (down == 0)] = 100.0
    out[valid & (down != 0) & (up == 0)] = 0.0
    return out


def supertrend(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    factor: float,
    atr_length: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Port of the indicator's `supertrend()` (itself a copy of TradingView's
    built-in). Returns `(supertrend_line, direction)`.

    direction is TradingView's convention, which reads backwards:
        -1 = UPTREND   (line = lower band, sitting below price)
        +1 = DOWNTREND (line = upper band, sitting above price)

    Two details that must not be "cleaned up":

    1. `prevLowerBand`/`prevUpperBand` read the previous bar's FINAL (already
       ratcheted) band, not its freshly computed one — in Pine a `:=`
       reassignment is what gets stored in series history. Hence the port
       carries `upper`/`lower` arrays and indexes [i-1] on them.
    2. `prevSuperTrend == prevUpperBand` is an exact float equality test.
       It looks fragile but is load-bearing: it is how the built-in remembers
       which side it was on, and both values are literally the same float
       assigned on the previous bar, so it compares equal. Replacing it with a
       tolerance changes the flips.
    """
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    close = np.asarray(close, dtype=float)
    n = len(close)

    atr_vals = atr(high, low, close, atr_length)
    st = np.full(n, np.nan)
    direction = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)

    for i in range(n):
        a = atr_vals[i]
        upper_band = close[i] + factor * a   # nan while ATR is still warming up
        lower_band = close[i] - factor * a

        prev_lower = nz(lower[i - 1]) if i > 0 else 0.0
        prev_upper = nz(upper[i - 1]) if i > 0 else 0.0
        prev_close = close[i - 1] if i > 0 else np.nan

        # lowerBand := lowerBand > prevLowerBand or close[1] < prevLowerBand
        #              ? lowerBand : prevLowerBand
        lower[i] = lower_band if (lower_band > prev_lower or prev_close < prev_lower) else prev_lower
        # upperBand := upperBand < prevUpperBand or close[1] > prevUpperBand
        #              ? upperBand : prevUpperBand
        upper[i] = upper_band if (upper_band < prev_upper or prev_close > prev_upper) else prev_upper

        prev_atr = atr_vals[i - 1] if i > 0 else np.nan
        prev_st = st[i - 1] if i > 0 else np.nan

        if np.isnan(prev_atr):
            direction[i] = 1.0
        elif prev_st == prev_upper:
            direction[i] = -1.0 if close[i] > upper[i] else 1.0
        else:
            direction[i] = 1.0 if close[i] < lower[i] else -1.0

        st[i] = lower[i] if direction[i] == -1.0 else upper[i]

    return st, direction


def crossover(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pine `ta.crossover(a, b)` — a[1] <= b[1] and a > b."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = np.zeros(len(a), dtype=bool)
    if len(a) > 1:
        out[1:] = (a[1:] > b[1:]) & (a[:-1] <= b[:-1])
    return out


def crossunder(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pine `ta.crossunder(a, b)` — a[1] >= b[1] and a < b."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    out = np.zeros(len(a), dtype=bool)
    if len(a) > 1:
        out[1:] = (a[1:] < b[1:]) & (a[:-1] >= b[:-1])
    return out
