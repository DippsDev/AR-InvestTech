"""Regression tests for the backtest-only incremental swing cache."""

from dataclasses import asdict, replace

import numpy as np

from trendline.config import TrendlineConfig
from trendline.strategy import SignalGenerator


def _line_dict(line):
    return None if line is None else asdict(line)


def test_incremental_candidates_match_full_prefix_scans():
    rng = np.random.default_rng(9173)
    closes = 10_000.0 + np.cumsum(rng.normal(0.0, 18.0, 300))
    half_ranges = rng.uniform(4.0, 30.0, len(closes))
    highs = closes + half_ranges
    lows = closes - half_ranges

    for lookback in (1, 2, 3, 5):
        cfg = replace(
            TrendlineConfig(),
            swing_lookback=lookback,
            obstruction_tolerance_points=7.5,
        )
        incremental = SignalGenerator(cfg, incremental_swings=True)
        legacy = SignalGenerator(cfg, incremental_swings=False)

        for bar_idx in range(len(closes)):
            actual = incremental._candidate_lines(bar_idx, highs, lows)
            expected = legacy._candidate_lines(bar_idx, highs, lows)
            assert tuple(map(_line_dict, actual)) == tuple(map(_line_dict, expected))


def test_incremental_cache_catches_up_after_skipped_bars():
    rng = np.random.default_rng(2201)
    closes = 100.0 + np.cumsum(rng.normal(0.0, 1.0, 300))
    highs = closes + rng.uniform(0.2, 1.5, len(closes))
    lows = closes - rng.uniform(0.2, 1.5, len(closes))
    cfg = replace(TrendlineConfig(), swing_lookback=3)
    incremental = SignalGenerator(cfg, incremental_swings=True)
    legacy = SignalGenerator(cfg, incremental_swings=False)

    for bar_idx in (25, 26, 80, 81, 179, 299):
        actual = incremental._candidate_lines(bar_idx, highs, lows)
        expected = legacy._candidate_lines(bar_idx, highs, lows)
        assert tuple(map(_line_dict, actual)) == tuple(map(_line_dict, expected))
