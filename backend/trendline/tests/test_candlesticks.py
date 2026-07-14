"""
Unit tests for reversal candlestick pattern detectors.

Each pattern gets a positive case, a near-miss/negative case, and (where
applicable) the opposite-direction case. All fixtures are small, hand-built
numpy arrays with inline comments explaining the shape of each candle.
"""
import numpy as np

from trendline.candlesticks import (
    classify_reversal,
    detect_doji,
    detect_engulfing,
    detect_hammer_shooting_star,
    detect_harami,
    detect_piercing_darkcloud,
    detect_railway_track,
    detect_spinning_top,
)


class TestEngulfing:
    def test_bullish_engulfing(self):
        # bar0: bearish 1.10 -> 1.08 (body 0.02). bar1: bullish 1.07 -> 1.12
        # (body 0.05), opens inside/below bar0's close and closes above bar0's open.
        opens  = np.array([1.10, 1.07])
        closes = np.array([1.08, 1.12])
        assert detect_engulfing(opens, closes, 1) == "bullish"

    def test_bearish_engulfing(self):
        # bar0: bullish 1.08 -> 1.10. bar1: bearish 1.11 -> 1.07, engulfing.
        opens  = np.array([1.08, 1.11])
        closes = np.array([1.10, 1.07])
        assert detect_engulfing(opens, closes, 1) == "bearish"

    def test_no_engulf_when_body_not_larger(self):
        # bar1's body (0.01) is smaller than bar0's (0.02) — not an engulfing.
        opens  = np.array([1.10, 1.085])
        closes = np.array([1.08, 1.095])
        assert detect_engulfing(opens, closes, 1) is None


class TestPiercingDarkCloud:
    def test_piercing_line(self):
        # bar0 bearish 1.10 -> 1.08 (mid = 1.09). bar1 opens at/below bar0's
        # close, closes between the midpoint and bar0's open.
        opens  = np.array([1.10, 1.075])
        closes = np.array([1.08, 1.095])
        assert detect_piercing_darkcloud(opens, closes, 1) == "bullish"

    def test_dark_cloud_cover(self):
        # bar0 bullish 1.08 -> 1.10 (mid = 1.09). bar1 opens at/above bar0's
        # close, closes between bar0's open and the midpoint.
        opens  = np.array([1.08, 1.105])
        closes = np.array([1.10, 1.085])
        assert detect_piercing_darkcloud(opens, closes, 1) == "bearish"

    def test_no_piercing_when_close_short_of_midpoint(self):
        # bar1 closes below bar0's midpoint (1.09) — doesn't clear the bar.
        opens  = np.array([1.10, 1.075])
        closes = np.array([1.08, 1.085])
        assert detect_piercing_darkcloud(opens, closes, 1) is None


class TestHarami:
    def test_bullish_harami(self):
        # bar0 bearish, big body [1.05, 1.10]. bar1's body fully inside it.
        opens  = np.array([1.10, 1.07])
        closes = np.array([1.05, 1.08])
        assert detect_harami(opens, closes, 1) == "bullish"

    def test_bearish_harami(self):
        # bar0 bullish, big body [1.05, 1.10]. bar1's body fully inside it.
        opens  = np.array([1.05, 1.07])
        closes = np.array([1.10, 1.08])
        assert detect_harami(opens, closes, 1) == "bearish"

    def test_no_harami_when_not_contained(self):
        # bar1's low (1.04) falls outside bar0's body range [1.05, 1.10].
        opens  = np.array([1.10, 1.04])
        closes = np.array([1.05, 1.08])
        assert detect_harami(opens, closes, 1) is None


class TestHammerShootingStar:
    def test_hammer(self):
        opens  = np.array([1.10])
        highs  = np.array([1.1015])
        lows   = np.array([1.08])
        closes = np.array([1.101])
        # body=0.001, upper wick=0.0005 (clearly <=body), lower wick=0.02
        # (clearly >=2x body) — margins kept well clear of float rounding.
        assert detect_hammer_shooting_star(opens, highs, lows, closes, 0) == "bullish"

    def test_shooting_star(self):
        opens  = np.array([1.10])
        highs  = np.array([1.122])
        lows   = np.array([1.0996])
        closes = np.array([1.101])
        # body=0.001, upper wick=0.021 (clearly >=2x body), lower wick=0.0004
        # (clearly <=body) — margins kept well clear of float rounding.
        assert detect_hammer_shooting_star(opens, highs, lows, closes, 0) == "bearish"

    def test_no_signal_when_body_too_large(self):
        opens  = np.array([1.10])
        highs  = np.array([1.12])
        lows   = np.array([1.10])
        closes = np.array([1.11])
        # body=0.01, range=0.02 -> body/range = 0.5, exceeds default 0.3 ceiling
        assert detect_hammer_shooting_star(opens, highs, lows, closes, 0) is None


class TestDoji:
    def test_dragonfly_is_bullish(self):
        opens  = np.array([1.10])
        highs  = np.array([1.1006])
        lows   = np.array([1.08])
        closes = np.array([1.1005])
        assert detect_doji(opens, highs, lows, closes, 0) == "bullish"

    def test_gravestone_is_bearish(self):
        opens  = np.array([1.10])
        highs  = np.array([1.12])
        lows   = np.array([1.0999])
        closes = np.array([1.1005])
        assert detect_doji(opens, highs, lows, closes, 0) == "bearish"

    def test_balanced_cross_has_no_bias(self):
        # body=0.0002, range=0.0022 (ratio 0.09, clears the 0.1 doji gate),
        # upper wick == lower wick == 0.0010 — perfectly balanced.
        opens  = np.array([1.1000])
        highs  = np.array([1.1012])
        lows   = np.array([1.0990])
        closes = np.array([1.1002])
        assert detect_doji(opens, highs, lows, closes, 0) is None

    def test_no_doji_when_body_too_large(self):
        opens  = np.array([1.10])
        highs  = np.array([1.13])
        lows   = np.array([1.09])
        closes = np.array([1.12])
        assert detect_doji(opens, highs, lows, closes, 0) is None


class TestSpinningTop:
    def test_balanced_small_body_is_neutral(self):
        opens  = np.array([1.10])
        highs  = np.array([1.103])
        lows   = np.array([1.098])
        closes = np.array([1.1005])
        assert detect_spinning_top(opens, highs, lows, closes, 0) == "neutral"

    def test_unbalanced_wicks_are_not_spinning_top(self):
        opens  = np.array([1.10])
        highs  = np.array([1.104])
        lows   = np.array([1.10])
        closes = np.array([1.1005])
        assert detect_spinning_top(opens, highs, lows, closes, 0) is None


class TestRailwayTrack:
    def _history_and_pattern(self, c1_bull: bool, c2_bull: bool):
        # 5 small-bodied history bars (avg body ~0.00034), then 2 long,
        # roughly equal, opposite-colour bars at the end.
        hist_opens  = [1.000, 1.001, 1.002, 1.0015, 1.002]
        hist_closes = [1.0005, 1.0015, 1.0025, 1.0018, 1.0022]
        if c1_bull:
            o1, c1 = 1.095, 1.145
        else:
            o1, c1 = 1.15, 1.10
        if c2_bull:
            o2, c2 = 1.095, 1.145
        else:
            o2, c2 = 1.15, 1.10
        opens  = np.array(hist_opens + [o1, o2])
        closes = np.array(hist_closes + [c1, c2])
        return opens, closes

    def test_bullish_railway_track(self):
        opens, closes = self._history_and_pattern(c1_bull=False, c2_bull=True)
        assert detect_railway_track(opens, closes, 6, avg_body_lookback=5) == "bullish"

    def test_bearish_railway_track(self):
        opens, closes = self._history_and_pattern(c1_bull=True, c2_bull=False)
        assert detect_railway_track(opens, closes, 6, avg_body_lookback=5) == "bearish"

    def test_no_signal_when_sizes_dont_match(self):
        hist_opens  = [1.000, 1.001, 1.002, 1.0015, 1.002]
        hist_closes = [1.0005, 1.0015, 1.0025, 1.0018, 1.0022]
        # bar5 has a long body, bar6's body is tiny — not "roughly equal".
        opens  = np.array(hist_opens + [1.15, 1.001])
        closes = np.array(hist_closes + [1.10, 1.0015])
        assert detect_railway_track(opens, closes, 6, avg_body_lookback=5) is None


class TestClassifyReversal:
    def test_dispatches_engulfing_first(self):
        opens  = np.array([1.10, 1.07])
        highs  = np.array([1.101, 1.121])
        lows   = np.array([1.079, 1.069])
        closes = np.array([1.08, 1.12])
        assert classify_reversal(opens, highs, lows, closes, 1) == "bullish"

    def test_none_when_nothing_matches(self):
        # bar0 is exactly flat (open == close) so none of the 2-candle
        # patterns' "opposite colour" branches can trigger; bar1 has a
        # moderate body (not doji/hammer/shooting-star shaped either).
        # Railway track needs 20 bars of history by default and this array
        # is too short, so it can't fire regardless of shape.
        opens  = np.array([1.1000, 1.1000])
        highs  = np.array([1.1000, 1.1015])
        lows   = np.array([1.1000, 1.0998])
        closes = np.array([1.1000, 1.1010])
        assert classify_reversal(opens, highs, lows, closes, 1) is None
