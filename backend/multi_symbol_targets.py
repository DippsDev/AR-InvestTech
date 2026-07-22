"""Live trading targets for the multi-symbol rollout.

Chosen from the 180-day, 11-symbol backtest campaign (see
backend/backtests/multi_sb_*.json / multi_tl_*.json), ranked by profit
factor — top 3 per strategy. US30m is deliberately excluded: it placed
#6/12 for Silver Bullet and outside the top 3 for Trendline, so it lost its
spot to better performers.

Threshold overrides scale US30's tuned point-based parameters (fvg size,
stop buffer, tolerances, min risk) by each symbol's median M5 bar range
relative to US30's over the same window (24.9 points) — the same
volatility-scaling approach used to make the backtest thresholds meaningful
across very different price scales (an index at ~50,000 vs. EURUSD at ~1.1).
"""

# symbol -> SilverBulletConfig field overrides
SB_TARGETS: dict[str, dict[str, float]] = {
    "DE30m":   dict(fvg_min_points=10.4578,   stop_buffer_points=0.373494,   min_risk_points=3.73494),
    "EURUSDm": dict(fvg_min_points=0.00015743, stop_buffer_points=0.0000056225, min_risk_points=0.0000562249),
    "GBPUSDm": dict(fvg_min_points=0.00021928, stop_buffer_points=0.0000078313, min_risk_points=0.0000783133),
}

# symbol -> TrendlineConfig field overrides
TL_TARGETS: dict[str, dict[str, float]] = {
    "DE30m":   dict(obstruction_tolerance_points=2.240964, breach_tolerance_points=3.734940,
                     touch_tolerance_points=2.240964, stop_buffer_points=3.734940, min_risk_points=11.204819),
    "USDJPYm": dict(obstruction_tolerance_points=0.0046988, breach_tolerance_points=0.0078313,
                     touch_tolerance_points=0.0046988, stop_buffer_points=0.0078313, min_risk_points=0.0234940),
    "USTECm":  dict(obstruction_tolerance_points=2.640964, breach_tolerance_points=4.401606,
                     touch_tolerance_points=2.640964, stop_buffer_points=4.401606, min_risk_points=13.204819),
}
