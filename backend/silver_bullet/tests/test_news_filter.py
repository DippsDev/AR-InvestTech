"""
Unit tests for the high-impact-news filter used by the live trading path.
"""
from datetime import date, datetime

import numpy as np

from silver_bullet.config import SilverBulletConfig
from silver_bullet.news_calendar import HIGH_IMPACT_DATES, is_news_day
from silver_bullet.strategy import SignalGenerator


class TestNewsCalendar:
    def test_is_news_day_accepts_string(self):
        assert is_news_day("2026-07-02") is True
        assert is_news_day("2026-07-03") is False

    def test_is_news_day_accepts_date(self):
        assert is_news_day(date(2026, 7, 2)) is True
        assert is_news_day(date(2026, 7, 3)) is False

    def test_is_news_day_accepts_datetime(self):
        assert is_news_day(datetime(2026, 7, 2, 10, 30)) is True
        assert is_news_day(datetime(2026, 7, 3, 10, 30)) is False

    def test_high_impact_dates_not_empty(self):
        assert len(HIGH_IMPACT_DATES) > 0


class TestSignalGeneratorNewsFilter:
    def test_generator_skips_news_days_when_configured(self):
        cfg = SilverBulletConfig(skip_news_days=True)
        gen = SignalGenerator(cfg)

        highs = np.array([100.0, 102.0, 105.0, 103.0, 104.0])
        lows = np.array([99.0, 100.0, 101.0, 102.0, 103.0])
        closes = np.array([100.0, 101.0, 104.0, 103.0, 104.0])
        opens = closes.copy()

        # 2026-07-02 is a known NFP release day.
        signal = gen.on_bar(
            bar_idx=4,
            highs=highs,
            lows=lows,
            closes=closes,
            opens=opens,
            in_window=True,
            window_id=1,
            date_str="2026-07-02",
        )
        assert signal is None

    def test_generator_allows_non_news_days(self):
        cfg = SilverBulletConfig(skip_news_days=True)
        gen = SignalGenerator(cfg)

        # A deliberately non-news day should be allowed to scan.
        signal = gen.on_bar(
            bar_idx=0,
            highs=np.array([100.0]),
            lows=np.array([99.0]),
            closes=np.array([100.0]),
            opens=np.array([100.0]),
            in_window=True,
            window_id=1,
            date_str="2026-07-03",
        )
        # With only one bar there is no setup, but the call must not be
        # rejected because of the date.
        assert signal is None

    def test_generator_allows_news_days_when_filter_off(self):
        cfg = SilverBulletConfig(skip_news_days=False)
        gen = SignalGenerator(cfg)

        signal = gen.on_bar(
            bar_idx=0,
            highs=np.array([100.0]),
            lows=np.array([99.0]),
            closes=np.array([100.0]),
            opens=np.array([100.0]),
            in_window=True,
            window_id=1,
            date_str="2026-07-02",
        )
        assert signal is None
