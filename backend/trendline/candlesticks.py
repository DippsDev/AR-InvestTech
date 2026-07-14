"""
Reversal candlestick pattern detectors — pure functions, no side-effects.

Each detector inspects 1-2 trailing bars ending at `idx` and returns
"bullish", "bearish", or None. Geometric definitions follow the source
material's own descriptions of each pattern; colour of the individual
candle only matters where the source material says it matters (e.g. the
doji variants), and is explicitly ignored elsewhere (hammer/shooting star,
railway track) per its own notes.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def _body(o: float, c: float) -> float:
    return abs(c - o)


def _range(h: float, l: float) -> float:
    return max(h - l, 1e-9)


def detect_doji(
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
    idx: int, body_ratio_max: float = 0.1,
) -> Optional[str]:
    """Dragonfly (long lower wick, near-flat top) -> bullish.
    Gravestone (long upper wick, near-flat bottom) -> bearish.
    Plain doji/cross (balanced wicks) -> None, no directional bias."""
    o, h, l, c = opens[idx], highs[idx], lows[idx], closes[idx]
    if _body(o, c) / _range(h, l) > body_ratio_max:
        return None
    upper = h - max(o, c)
    lower = min(o, c) - l
    if lower > upper * 2:
        return "bullish"
    if upper > lower * 2:
        return "bearish"
    return None


def detect_engulfing(opens: np.ndarray, closes: np.ndarray, idx: int) -> Optional[str]:
    """2nd candle's body exceeds and engulfs the 1st's, opposite colour."""
    if idx < 1:
        return None
    o1, c1, o2, c2 = opens[idx - 1], closes[idx - 1], opens[idx], closes[idx]
    if c1 < o1 and c2 > o2 and o2 <= c1 and c2 >= o1 and _body(o2, c2) > _body(o1, c1):
        return "bullish"
    if c1 > o1 and c2 < o2 and o2 >= c1 and c2 <= o1 and _body(o2, c2) > _body(o1, c1):
        return "bearish"
    return None


def detect_piercing_darkcloud(opens: np.ndarray, closes: np.ndarray, idx: int) -> Optional[str]:
    """Piercing line (bullish) / dark cloud cover (bearish): 2-candle, opposite
    colours, 2nd candle closes beyond the 50% mark of the 1st's body."""
    if idx < 1:
        return None
    o1, c1, o2, c2 = opens[idx - 1], closes[idx - 1], opens[idx], closes[idx]
    mid1 = (o1 + c1) / 2
    if c1 < o1 and c2 > o2 and o2 <= c1 and mid1 < c2 < o1:
        return "bullish"
    if c1 > o1 and c2 < o2 and o2 >= c1 and o1 < c2 < mid1:
        return "bearish"
    return None


def detect_harami(opens: np.ndarray, closes: np.ndarray, idx: int) -> Optional[str]:
    """2nd candle's full body ("inside bar") contained within the 1st's body."""
    if idx < 1:
        return None
    o1, c1, o2, c2 = opens[idx - 1], closes[idx - 1], opens[idx], closes[idx]
    lo1, hi1 = min(o1, c1), max(o1, c1)
    lo2, hi2 = min(o2, c2), max(o2, c2)
    if hi1 == lo1:
        return None  # no real body on the first candle to be "inside" of
    if lo2 > lo1 and hi2 < hi1:
        return "bullish" if c1 < o1 else "bearish"
    return None


def detect_hammer_shooting_star(
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, idx: int,
    wick_ratio_min: float = 2.0, body_ratio_max: float = 0.3,
) -> Optional[str]:
    """Small body near one end of the range, long opposite-side wick.
    Colour does not matter, per the source material."""
    o, h, l, c = opens[idx], highs[idx], lows[idx], closes[idx]
    body, rng = _body(o, c), _range(h, l)
    if body / rng > body_ratio_max:
        return None
    upper = h - max(o, c)
    lower = min(o, c) - l
    if lower >= wick_ratio_min * body and upper <= body:
        return "bullish"   # hammer
    if upper >= wick_ratio_min * body and lower <= body:
        return "bearish"   # shooting star
    return None


def detect_spinning_top(
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, idx: int,
    body_ratio_max: float = 0.3, wick_balance_tol: float = 0.3,
) -> Optional[str]:
    """Small body, roughly balanced wicks both sides — indecision.

    Per the source material this is too weak to stand alone as confirmation,
    so it always returns "neutral" (never "bullish"/"bearish") and is never
    dispatched by classify_reversal — kept here for future context-dependent
    use (e.g. combined with a stronger pattern), not as a standalone signal.
    """
    o, h, l, c = opens[idx], highs[idx], lows[idx], closes[idx]
    body, rng = _body(o, c), _range(h, l)
    upper = h - max(o, c)
    lower = min(o, c) - l
    if body / rng <= body_ratio_max and abs(upper - lower) <= wick_balance_tol * rng:
        return "neutral"
    return None


def detect_railway_track(
    opens: np.ndarray, closes: np.ndarray, idx: int,
    length_ratio_min: float = 1.5, avg_body_lookback: int = 20,
    size_match_tol: float = 0.2,
) -> Optional[str]:
    """Two consecutive opposite-colour candles, both unusually long vs. the
    rolling average body length, roughly equal size to each other."""
    if idx < 1 or idx - 1 - avg_body_lookback < 0:
        return None
    hist_opens = opens[idx - 1 - avg_body_lookback: idx - 1]
    hist_closes = closes[idx - 1 - avg_body_lookback: idx - 1]
    if len(hist_opens) == 0:
        return None
    avg_body = float(np.mean(np.abs(hist_closes - hist_opens)))
    if avg_body <= 0:
        return None

    o1, c1, o2, c2 = opens[idx - 1], closes[idx - 1], opens[idx], closes[idx]
    b1, b2 = _body(o1, c1), _body(o2, c2)

    same_size = abs(b1 - b2) <= size_match_tol * max(b1, b2)
    long_enough = b1 >= length_ratio_min * avg_body and b2 >= length_ratio_min * avg_body
    if not (same_size and long_enough):
        return None

    c1_bull, c2_bull = c1 > o1, c2 > o2
    if not c1_bull and c2_bull:
        return "bullish"
    if c1_bull and not c2_bull:
        return "bearish"
    return None


def classify_reversal(
    opens: np.ndarray, highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, idx: int,
    body_ratio_max: float = 0.3, wick_ratio_min: float = 2.0,
    railway_length_ratio_min: float = 1.5, avg_body_lookback: int = 20,
) -> Optional[str]:
    """Run the 7 reversal detectors in priority order (strongest/most
    2-candle-confirmed patterns first, doji last) and return the first
    "bullish"/"bearish" match, or None. Spinning top is intentionally never
    dispatched here — see detect_spinning_top's docstring."""
    result = detect_engulfing(opens, closes, idx)
    if result:
        return result
    result = detect_piercing_darkcloud(opens, closes, idx)
    if result:
        return result
    result = detect_harami(opens, closes, idx)
    if result:
        return result
    result = detect_railway_track(opens, closes, idx, railway_length_ratio_min, avg_body_lookback)
    if result:
        return result
    result = detect_hammer_shooting_star(opens, highs, lows, closes, idx, wick_ratio_min, body_ratio_max)
    if result:
        return result
    result = detect_doji(opens, highs, lows, closes, idx, body_ratio_max=0.1)
    if result:
        return result
    return None
