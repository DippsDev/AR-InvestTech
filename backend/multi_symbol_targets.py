"""Live trading targets for the multi-symbol rollout.

Chosen from the 180-day, 11-symbol backtest campaign (see
backend/backtests/multi_sb_*.json / multi_tl_*.json), ranked by profit
factor — top 3 per strategy. US30m is deliberately excluded: it placed
#6/12 for Silver Bullet and outside the top 3 for Trendline, so it lost its
spot to better performers.

XAUUSDm was added to SB_TARGETS on 2026-08-15 after a dedicated evaluation
(backtests/sb_candidate_eval.py): over the full ~17-month M5 history with
the current live config it ran PF 2.56 / +$632 / 65% win rate (23 trades),
and PF 3.10 over the recent 180-day campaign window — above GBPUSDm's
numbers, making it SB's third-best instrument. Its Trendline results were
negative in the recent window (PF 0.77–0.89), so it belongs to SB only.
USTECm was evaluated for SB at the same time and rejected (PF 1.37 full
history, 0.39 recent) — it stays Trendline-only, where its evidence is
stronger (PF 1.79).

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
    "XAUUSDm": dict(fvg_min_points=3.19639,   stop_buffer_points=0.114157,   min_risk_points=1.14157),
}

# symbol -> TrendlineConfig field overrides
#
# touch/obstruction tolerance is 3x the volatility-scaled base on DE30m and
# USTECm. The scaling below makes every symbol's tolerance the same fraction of
# its own bar range, but that fraction is inherited from TrendlineConfig's
# US30 defaults, which its own docstring flags as never having been backtested.
# At 1x it lands at ~6.4% of a median H1 bar and the touch gate almost never
# opens: over 180 days DE30m saw 2,014 bars carrying a live support line and
# 402 bullish reversal candles, but only 19 touches. Re-measured across a
# 1x-8x sweep with each symbol's campaign costs:
#
#            1x                 3x                 8x
#   DE30m     5tr PF 4.27       23tr PF 1.58       52tr PF 0.85
#   USTECm    7tr PF 1.58       21tr PF 1.19       61tr PF 0.84
#   USDJPYm  19tr PF 2.98       41tr PF 1.14       82tr PF 0.96
#
# 3x is where DE30m and USTECm buy 3-4x the trades for the same net profit;
# by 8x every symbol is losing money, so this is a ridge, not a free knob.
# USDJPYm is deliberately left at 1x — it is the one symbol already at its
# own optimum, and widening it cuts net from $1,933 to $404. Do not
# "harmonise" the three.
TL_TARGETS: dict[str, dict[str, float]] = {
    "DE30m":   dict(obstruction_tolerance_points=6.722892, breach_tolerance_points=3.734940,
                     touch_tolerance_points=6.722892, stop_buffer_points=3.734940, min_risk_points=11.204819),
    "USDJPYm": dict(obstruction_tolerance_points=0.0046988, breach_tolerance_points=0.0078313,
                     touch_tolerance_points=0.0046988, stop_buffer_points=0.0078313, min_risk_points=0.0234940),
    "USTECm":  dict(obstruction_tolerance_points=7.922892, breach_tolerance_points=4.401606,
                     touch_tolerance_points=7.922892, stop_buffer_points=4.401606, min_risk_points=13.204819),
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
