"""
Unit tests for SignalGenerator's bar-by-bar state machine.

skip_news_days is left False in every test config below purely so the
fixture dates (which aren't real trading days) can't accidentally collide
with an entry in silver_bullet's HIGH_IMPACT_DATES calendar.
"""
import numpy as np
import pytest

from trendline.config import TrendlineConfig
from trendline.indicators import TrendLine
from trendline.strategy import SignalGenerator


def _base_cfg(**overrides) -> TrendlineConfig:
    cfg = TrendlineConfig(
        swing_lookback=2,
        avg_range_lookback=20,
        steepness_max_ratio=1.0,
        obstruction_tolerance_points=0.001,
        breach_tolerance_points=0.01,
        touch_tolerance_points=0.005,
        candle_body_ratio_max=0.3,
        candle_wick_ratio_min=2.0,
        railway_length_ratio_min=1.5,
        avg_body_lookback=5,
        stop_buffer_points=0.005,
        min_risk_points=0.01,
        target_mode="rr",
        rr=3.0,
        min_rr_for_swing_target=3.0,
        one_trade_at_a_time=True,
        skip_news_days=False,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class TestNoSignalWithoutTouchOrPattern:
    def test_flat_market_never_signals(self):
        # Constant OHLC -> no swing points ever confirmed -> no trendline is
        # ever built -> on_bar must return None regardless of bar count.
        n = 15
        opens  = np.full(n, 1.1000)
        highs  = np.full(n, 1.1005)
        lows   = np.full(n, 1.0995)
        closes = np.full(n, 1.1000)

        gen = SignalGenerator(_base_cfg())
        for i in range(n):
            signal = gen.on_bar(i, highs, lows, closes, opens, date_str="2024-01-01")
            assert signal is None


def _touch_and_engulf_fixture():
    """Bars 0-10 build an ascending support line from confirmed swing lows
    at bar 2 (1.05) and bar 8 (1.07); bars 0-9 are flat/no-op candles so no
    pattern or line exists before the line is even buildable (bar 10).
    Bar 11 touches the line's extrapolated value (1.08) with a textbook
    bullish engulfing candle against bar 10."""
    lows  = [1.10, 1.09, 1.05, 1.09, 1.10, 1.09, 1.08, 1.09, 1.07, 1.09, 1.10, 1.078]
    highs = [l + 0.02 for l in lows[:-1]] + [1.16]  # bar 11 gets a taller range
    opens  = [lows[i] + 0.005 for i in range(10)] + [1.115, 1.10]
    closes = [lows[i] + 0.005 for i in range(10)] + [1.105, 1.14]
    return (
        np.array(opens), np.array(highs), np.array(lows), np.array(closes)
    )


class TestSignalFiresOnTouchPlusPattern:
    def test_bullish_engulfing_touch_fires_long_signal(self):
        opens, highs, lows, closes = _touch_and_engulf_fixture()
        gen = SignalGenerator(_base_cfg())

        signal = None
        for i in range(len(opens)):
            signal = gen.on_bar(i, highs, lows, closes, opens, date_str="2024-01-01")
            if i < len(opens) - 1:
                assert signal is None, f"unexpected signal at bar {i}"

        assert signal is not None
        assert signal.direction == "long"
        assert signal.pattern == "bullish"
        assert signal.entry_price == pytest.approx(1.14)
        assert signal.stop_price == pytest.approx(1.078 - 0.005)


class TestOneTradeAtATimeGate:
    def test_gate_blocks_until_trade_closed(self):
        opens, highs, lows, closes = _touch_and_engulf_fixture()
        gen = SignalGenerator(_base_cfg())

        last_idx = len(opens) - 1
        for i in range(last_idx):
            assert gen.on_bar(i, highs, lows, closes, opens, date_str="2024-01-01") is None

        first_signal = gen.on_bar(last_idx, highs, lows, closes, opens, date_str="2024-01-01")
        assert first_signal is not None

        # Simulate the live adapter's success callback — the gate should now
        # block an identical re-processing of the same touch bar.
        gen.notify_trade_opened()
        blocked = gen.on_bar(last_idx, highs, lows, closes, opens, date_str="2024-01-01")
        assert blocked is None

        # Once the position is reported closed, the same touch can fire again.
        gen.notify_trade_closed()
        reopened = gen.on_bar(last_idx, highs, lows, closes, opens, date_str="2024-01-01")
        assert reopened is not None
        assert reopened.direction == "long"


class TestTargetModeFallback:
    def test_falls_back_to_rr_when_no_opposite_swing_exists(self):
        cfg = _base_cfg(target_mode="opposite_swing", rr=3.0, min_rr_for_swing_target=3.0)
        gen = SignalGenerator(cfg)

        # Perfectly flat highs -> no confirmed swing high exists anywhere,
        # so nearest_buyside_liquidity() has nothing to return.
        highs  = np.full(10, 1.020)
        lows   = np.full(10, 1.000)
        closes = np.full(10, 1.019)

        line = TrendLine(
            kind="support", anchor1_bar=0, anchor1_price=1.00,
            anchor2_bar=5, anchor2_price=1.01, slope=0.002,
        )
        signal = gen._build_signal(
            "long", line, bar_idx=9, highs=highs, lows=lows, closes=closes,
            pattern="bullish", date_str="2024-01-01",
        )

        assert signal is not None
        risk = 1.019 - (1.000 - cfg.stop_buffer_points)
        assert signal.target_price == pytest.approx(1.019 + cfg.rr * risk)
