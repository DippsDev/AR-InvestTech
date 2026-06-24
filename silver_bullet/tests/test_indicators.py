"""
Unit tests for indicators.py.

Every test feeds a small, hand-constructed candle sequence and asserts:
  - known swing highs / lows are found
  - known FVGs are found
  - known sweeps are found
  - non-qualifying inputs return None / False
"""
import numpy as np
import pytest

from silver_bullet.indicators import (
    is_swing_high,
    is_swing_low,
    get_swing_highs,
    get_swing_lows,
    detect_bullish_fvg,
    detect_bearish_fvg,
    detect_sellside_sweep,
    detect_buyside_sweep,
    fvg_entry_price,
    nearest_buyside_liquidity,
    nearest_sellside_liquidity,
)


# ============================================================
# Helpers
# ============================================================

def flat_bar(price: float):
    """Return (open, high, low, close) as a flat bar at `price`."""
    return price, price, price, price


# ============================================================
# is_swing_high / is_swing_low
# ============================================================

class TestSwingPointDetection:
    def _highs(self):
        #       0     1     2     3     4     5     6
        return np.array([100., 102., 110., 104., 106., 103., 101.])

    def _lows(self):
        # Bar 2 (95) is lowest in its lookback=2 neighbourhood: right=[97, 99] both > 95
        #       0     1     2     3     4     5     6
        return np.array([100.,  98.,  95.,  97.,  99.,  96.,  98.])

    def test_swing_high_found(self):
        # bar 2 (110) is the highest with lookback=2
        assert is_swing_high(self._highs(), idx=2, lookback=2)

    def test_swing_high_not_at_edge(self):
        # bar 0 has no left-side bars → not a confirmed swing high
        assert not is_swing_high(self._highs(), idx=0, lookback=2)

    def test_swing_high_wrong_bar(self):
        # bar 3 (104) is lower than bar 2 on the left → not a swing high
        assert not is_swing_high(self._highs(), idx=3, lookback=2)

    def test_swing_low_found(self):
        # bar 2 (95) is the lowest with lookback=2
        assert is_swing_low(self._lows(), idx=2, lookback=2)

    def test_swing_low_not_at_edge(self):
        assert not is_swing_low(self._lows(), idx=0, lookback=2)

    def test_get_swing_highs_returns_correct(self):
        highs = np.array([100., 102., 110., 104., 106., 103., 101.])
        result = get_swing_highs(highs, lookback=2)
        indices = [i for i, _ in result]
        assert 2 in indices  # 110 is a confirmed swing high

    def test_get_swing_lows_returns_correct(self):
        # Two distinct valleys: bar 2 (95) and bar 5 (70)
        lows = np.array([100., 98., 95., 97., 99., 70., 73., 80., 82.])
        result = get_swing_lows(lows, lookback=2)
        indices = [i for i, _ in result]
        assert 2 in indices  # 95 is a confirmed swing low (right=[97,99] both >95)
        assert 5 in indices  # 70 is a confirmed swing low

    def test_swing_high_strict_greater_than(self):
        # Tie on the left — not a swing high (must be strictly greater)
        highs = np.array([110., 110., 110., 104., 101.])
        assert not is_swing_high(highs, idx=0, lookback=1)
        assert not is_swing_high(highs, idx=1, lookback=1)
        assert not is_swing_high(highs, idx=2, lookback=1)


# ============================================================
# Fair Value Gap detection
# ============================================================

class TestFVGDetection:
    """
    Bullish FVG: low[idx] > high[idx-2]   →  zone = (high[idx-2], low[idx])
    Bearish FVG: high[idx] < low[idx-2]   →  zone = (high[idx], low[idx-2])
    """

    def test_bullish_fvg_detected(self):
        # Bars (high, low):
        #   0: h=105, l=100
        #   1: h=112, l=103   (middle, irrelevant to gap check)
        #   2: h=120, l=108   ← low[2]=108 > high[0]=105  ✓
        highs = np.array([105., 112., 120.])
        lows  = np.array([100., 103., 108.])
        result = detect_bullish_fvg(highs, lows, idx=2, fvg_min_points=2.0)
        assert result == (105.0, 108.0)

    def test_bullish_fvg_gap_too_small(self):
        highs = np.array([105., 112., 120.])
        lows  = np.array([100., 103., 106.])  # gap = 106-105 = 1 < min_points=2
        result = detect_bullish_fvg(highs, lows, idx=2, fvg_min_points=2.0)
        assert result is None

    def test_bullish_fvg_no_gap(self):
        # low[2]=104 < high[0]=105 → no gap
        highs = np.array([105., 112., 120.])
        lows  = np.array([100., 103., 104.])
        assert detect_bullish_fvg(highs, lows, idx=2, fvg_min_points=2.0) is None

    def test_bearish_fvg_detected(self):
        # Bars (high, low):
        #   0: h=120, l=115
        #   1: h=112, l=108   (middle)
        #   2: h=105, l=100   ← high[2]=105 < low[0]=115  ✓
        highs = np.array([120., 112., 105.])
        lows  = np.array([115., 108., 100.])
        result = detect_bearish_fvg(highs, lows, idx=2, fvg_min_points=5.0)
        assert result == (105.0, 115.0)

    def test_bearish_fvg_gap_too_small(self):
        highs = np.array([120., 112., 118.])  # gap = 120-118 = 2 < 5
        lows  = np.array([115., 108., 113.])
        assert detect_bearish_fvg(highs, lows, idx=2, fvg_min_points=5.0) is None

    def test_bearish_fvg_no_gap(self):
        highs = np.array([120., 112., 116.])  # high[2]=116 > low[0]=115
        lows  = np.array([115., 108., 110.])
        assert detect_bearish_fvg(highs, lows, idx=2, fvg_min_points=2.0) is None

    def test_fvg_requires_at_least_3_bars(self):
        highs = np.array([105., 112.])
        lows  = np.array([100., 103.])
        assert detect_bullish_fvg(highs, lows, idx=1, fvg_min_points=2.0) is None
        assert detect_bearish_fvg(highs, lows, idx=1, fvg_min_points=2.0) is None


# ============================================================
# Sweep detection
# ============================================================

class TestSweepDetection:
    """
    Build candle sequences with a known swing, then confirm that:
      - a wick-sweep is detected
      - a clean breakout (body below swing) is NOT a sweep
      - a bar that doesn't touch the swing is not detected
    """

    def _build_sellside_sweep_sequence(self):
        """
        Design (lookback=2, sweep_lookback=10):
          Bars 0-6: create context
          Bar 4: clear swing low (confirmed once bars 4+2=6 close)
          Bar 7: current bar — wicks below bar-4's low, closes above it.

        lows:  [100, 102, 103, 101, 95, 98, 99, 92→close@97]
                0    1    2    3   [4]  5   6   [7 current]
        """
        # We need highs and closes too for the sweep check
        lows   = np.array([100., 102., 103., 101.,  95.,  98.,  99.,  92.])
        closes = np.array([100., 102., 103., 101.,  96.,  98.,  99.,  97.])
        highs  = np.array([105., 107., 108., 106., 100., 103., 104., 103.])
        return highs, lows, closes

    def test_sellside_sweep_detected(self):
        highs, lows, closes = self._build_sellside_sweep_sequence()
        current_bar = 7
        result = detect_sellside_sweep(lows, closes, current_bar, swing_lookback=2, sweep_lookback=10)
        # bar-4 low is 95; current bar low=92 < 95 and close=97 > 95 → sweep
        assert result == pytest.approx(95.0)

    def test_sellside_sweep_clean_breakout_not_detected(self):
        """If the close is also below the swing low → breakout, not a sweep."""
        highs, lows, closes = self._build_sellside_sweep_sequence()
        # Change close to 93 (still below the swing low of 95)
        closes = closes.copy()
        closes[7] = 93.0
        result = detect_sellside_sweep(lows, closes, 7, swing_lookback=2, sweep_lookback=10)
        assert result is None

    def test_sellside_sweep_no_pierce(self):
        """Bar low doesn't reach the swing low → no sweep."""
        highs, lows, closes = self._build_sellside_sweep_sequence()
        lows = lows.copy()
        lows[7] = 96.0  # 96 > 95, doesn't pierce swing low
        result = detect_sellside_sweep(lows, closes, 7, swing_lookback=2, sweep_lookback=10)
        assert result is None

    def _build_buyside_sweep_sequence(self):
        """
        Bar 4: clear swing high (confirmed once bars 4+2=6 close)
        Bar 7: current bar — wicks above bar-4's high, closes below it.

        highs: [100, 98, 97, 99, 110, 106, 104, 115→close@108]
        """
        highs  = np.array([100.,  98.,  97.,  99., 110., 106., 104., 115.])
        closes = np.array([100.,  98.,  97.,  99., 108., 106., 104., 108.])
        lows   = np.array([ 95.,  93.,  92.,  94., 103., 100.,  98., 102.])
        return highs, lows, closes

    def test_buyside_sweep_detected(self):
        highs, lows, closes = self._build_buyside_sweep_sequence()
        result = detect_buyside_sweep(highs, closes, 7, swing_lookback=2, sweep_lookback=10)
        # bar-4 high=110; current bar high=115>110, close=108<110 → sweep
        assert result == pytest.approx(110.0)

    def test_buyside_sweep_clean_breakout_not_detected(self):
        highs, lows, closes = self._build_buyside_sweep_sequence()
        closes = closes.copy()
        closes[7] = 112.0  # closes above swing high → breakout, not sweep
        result = detect_buyside_sweep(highs, closes, 7, swing_lookback=2, sweep_lookback=10)
        assert result is None

    def test_buyside_sweep_no_pierce(self):
        highs, lows, closes = self._build_buyside_sweep_sequence()
        highs = highs.copy()
        highs[7] = 109.0  # doesn't exceed 110
        result = detect_buyside_sweep(highs, closes, 7, swing_lookback=2, sweep_lookback=10)
        assert result is None

    def test_sweep_not_found_when_swing_not_confirmed(self):
        """Swing at bar 4 is NOT yet confirmed at current_bar=5 (needs bar 6 to close)."""
        highs, lows, closes = self._build_sellside_sweep_sequence()
        result = detect_sellside_sweep(lows, closes, 5, swing_lookback=2, sweep_lookback=10)
        # Bar 4 swing low not confirmed (right side not fully closed by bar 5)
        assert result is None


# ============================================================
# FVG entry price
# ============================================================

class TestFVGEntryPrice:
    def test_bullish_near_edge(self):
        # For bullish: near edge = top of gap (lows[idx])
        price = fvg_entry_price(100.0, 108.0, "bullish", "near_edge")
        assert price == pytest.approx(108.0)

    def test_bullish_far_edge(self):
        price = fvg_entry_price(100.0, 108.0, "bullish", "far_edge")
        assert price == pytest.approx(100.0)

    def test_bullish_mid(self):
        price = fvg_entry_price(100.0, 108.0, "bullish", "mid")
        assert price == pytest.approx(104.0)

    def test_bearish_near_edge(self):
        # For bearish: near edge = bottom of gap (highs[idx])
        price = fvg_entry_price(95.0, 110.0, "bearish", "near_edge")
        assert price == pytest.approx(95.0)

    def test_bearish_far_edge(self):
        price = fvg_entry_price(95.0, 110.0, "bearish", "far_edge")
        assert price == pytest.approx(110.0)

    def test_bearish_mid(self):
        price = fvg_entry_price(95.0, 110.0, "bearish", "mid")
        assert price == pytest.approx(102.5)

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError):
            fvg_entry_price(100.0, 110.0, "sideways", "near_edge")

    def test_invalid_entry_mode_raises(self):
        with pytest.raises(ValueError):
            fvg_entry_price(100.0, 110.0, "bullish", "random_mode")


# ============================================================
# Nearest liquidity
# ============================================================

class TestNearestLiquidity:
    def test_nearest_buyside(self):
        # Confirmed swing highs above entry price
        # highs: swing at idx=2 (val=120), idx=5 (val=130), idx=8 (val=125)
        highs = np.array([100., 110., 120., 115., 118., 130., 122., 119., 125., 121., 118., 115.])
        # current_bar=11, swing_lookback=2 → confirmed up to bar 11-2-1=8
        result = nearest_buyside_liquidity(highs, current_bar=11, swing_lookback=2, above_price=118.0)
        # Swings above 118: 120, 130, 125 → nearest = 120
        assert result == pytest.approx(120.0)

    def test_nearest_sellside(self):
        lows = np.array([100., 90., 80., 85., 88., 70., 75., 78., 72., 76., 79., 82.])
        result = nearest_sellside_liquidity(lows, current_bar=11, swing_lookback=2, below_price=79.0)
        # Swing lows below 79: need to check which bars are confirmed swings
        # bar 2: low=80, bar 5: low=70, bar 8: low=72 — look for those below 79
        assert result is not None
        assert result < 79.0

    def test_no_liquidity_above(self):
        highs = np.array([100., 90., 80., 85., 88., 70., 75., 78., 72.])
        result = nearest_buyside_liquidity(highs, current_bar=8, swing_lookback=2, above_price=200.0)
        assert result is None
