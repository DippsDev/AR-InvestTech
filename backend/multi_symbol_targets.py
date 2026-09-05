"""Live trading targets for the multi-symbol rollout.

Silver Bullet symbols were rebuilt after an Aggressive-mode scan (extra
London + 13:30 ET windows, multiple trades per window, volatility-scaled
FVG/stop). On that screen FX majors went 0% win rate; USTECm stayed
profitable under Aggressive (PF 6.2) even though core-window-only was
stronger.

EURUSDm / GBPUSDm were therefore dropped. US30m stays out of SB (it placed
#6/12 on the original 180-day campaign and Aggressive did not lift it).
XAUUSDm stays: it was added on 2026-08-15 after a dedicated evaluation
(backtests/sb_candidate_eval.py) at PF 2.56 full history / 3.10 recent, and
that result was not part of the FX cull. USTECm's earlier core-window SB
rejection (PF 1.37 / 0.39) is overridden by the Aggressive screen.

DE30m was dropped from SB on 2026-09-05. On the current Yahoo M5 sample
(2026-05-27 → 2026-08-18) SB DE30m was 1/3 wins, PF 0.11, −$97.60 — the
only live SB name that finished net negative. The same tape on Trendline
was 4/5 wins, PF 16.21, so DE30m stays in TL_TARGETS only.

Trendline / Mutanabby lists are unchanged from the 180-day campaign.

Threshold overrides scale US30's tuned point-based parameters (fvg size,
stop buffer, tolerances, min risk) by each symbol's median M5 bar range
relative to US30's (24.9 points).
"""

# symbol -> SilverBulletConfig field overrides
SB_TARGETS: dict[str, dict[str, float]] = {
    "XAUUSDm": dict(fvg_min_points=3.19639,   stop_buffer_points=0.114157,   min_risk_points=1.14157),
    "USTECm":  dict(fvg_min_points=15.4618,   stop_buffer_points=0.552209,   min_risk_points=5.52209),
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
#
# ETHUSDm was added 2026-09-05 as the 24/7 weekend book. On the last 180 days
# of stored M5 (resampled to H1) it is the only crypto name that cleared the
# same bar as the live MB set: 21 trades, PF 1.27, +$365. BTCUSDm failed that
# screen on MB (PF 0.52) and both coins failed Silver Bullet and Trendline,
# so they stay off those lists.
MB_TARGETS: dict[str, dict[str, float]] = {
    "US30m":   dict(sensitivity=6.0, rr=2.0),
    "JP225m":  dict(sensitivity=6.0, rr=2.0),
    "USDJPYm": dict(sensitivity=6.0, rr=2.0),
    "ETHUSDm": dict(sensitivity=6.0, rr=2.0),
}
