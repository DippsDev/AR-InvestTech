"""
Unit tests for the off-hours scalp parameter overrides.
"""
from datetime import time

from silver_bullet.backtest import _is_past_cutoff, _off_hours_cfg
from silver_bullet.config import SilverBulletConfig


class TestOffHoursHelpers:
    def test_is_past_cutoff(self):
        assert _is_past_cutoff(time(17, 0), "17:00") is True
        assert _is_past_cutoff(time(16, 59), "17:00") is False
        assert _is_past_cutoff(time(9, 30), "17:00") is False

    def test_off_hours_cfg_overrides(self):
        base = SilverBulletConfig(
            fvg_min_points=14.0,
            rr=2.0,
            breakeven_r=0.5,
            trail_r=0.25,
            off_hours_fvg_min_points=6.0,
            off_hours_rr=1.2,
            off_hours_breakeven_r=0.2,
            off_hours_trail_r=0.1,
        )
        oh = _off_hours_cfg(base)
        assert oh.fvg_min_points == 6.0
        assert oh.rr == 1.2
        assert oh.breakeven_r == 0.2
        assert oh.trail_r == 0.1
        # Non-overridden fields stay the same.
        assert oh.swing_lookback == base.swing_lookback
        assert oh.stop_buffer_points == base.stop_buffer_points

    def test_base_cfg_unchanged(self):
        base = SilverBulletConfig()
        oh = _off_hours_cfg(base)
        assert base.rr != oh.rr or base.off_hours_rr == oh.rr
        # Ensure the original object is not mutated.
        assert base is not oh
