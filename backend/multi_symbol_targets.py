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

# symbol -> MutanabbyConfig field overrides
#
# Chosen from the 12-symbol H1 breadth run in backend/mutanabby/README.md.
# US30m had the best profit factor overall (1.60); JP225m and USDJPYm (both
# 1.37) are the strongest of the ten instruments that took no part in choosing
# these parameters, so their results carry no selection bias.
#
# Unlike SB_TARGETS/TL_TARGETS there are no per-symbol threshold overrides to
# compute here: Mutanabby's stop is ATR-derived and therefore already scales
# itself to each instrument's volatility. Every symbol gets the same settings,
# and they are identical across symbols on purpose — a per-symbol tuning pass
# on ~56 trades apiece would be fitting noise.
#
# sensitivity 6.0 (not the indicator's own default of 4.0) sits at the peak of
# a broad 5.0-7.0 ridge; rr 2.0 is the middle of the three TP rungs the
# indicator draws. Everything else stays at MutanabbyConfig's chart-faithful
# defaults, including no breakeven and no trailing stop — that is the exact
# configuration the reported profit factors were measured with.
MB_TARGETS: dict[str, dict[str, float]] = {
    "US30m":   dict(sensitivity=6.0, rr=2.0),
    "JP225m":  dict(sensitivity=6.0, rr=2.0),
    "USDJPYm": dict(sensitivity=6.0, rr=2.0),
}
