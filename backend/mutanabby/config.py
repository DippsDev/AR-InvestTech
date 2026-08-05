"""All strategy tunables in one place. Change here; nowhere else.

Every default below is the value the Pine indicator actually uses, so a
zero-argument MutanabbyConfig() reproduces the chart faithfully. Two of them
are values a TradingView user CANNOT change from the settings panel:

  * `supertrend_atr_length` — the script calls supertrend(close, sensitivity, 11)
    with a literal 11. Its own "ATR Length" input (14) is shadowed by the
    function parameter of the same name and only ever reaches the SL/TP maths.
  * `trend_sma_length` — the SMA(13) filter, named `sma9` in the source.

Unlike SilverBulletConfig's defaults (tuned against 3 years of US30 M5), these
are the indicator author's numbers, not backtested by us. `rr`, the management
fields and `exit_on_opposite_signal` have no counterpart in the indicator at
all — it draws 1:1/2:1/3:1 labels and never states which to take, so those are
ours and start deliberately plain.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MutanabbyConfig:
    # ── Instrument ────────────────────────────────────────────────────────────
    symbol: str = "US30"
    bars_lookback: int = 300   # bars fetched per cycle by a future live adapter

    # ── SuperTrend ────────────────────────────────────────────────────────────
    # Pine "Sensitivity" input (band multiplier). Lower = tighter = more flips.
    sensitivity: float = 4.0
    # Hardcoded at the Pine call site; NOT the user-facing "ATR Length" input.
    supertrend_atr_length: int = 11

    # ── Trend filter ──────────────────────────────────────────────────────────
    # `bull` also requires close >= SMA(n); `bear` requires close <= SMA(n).
    #
    # Measured on the stored history, this filter is very nearly INERT at the
    # default sensitivity: it removes 2 of 940 US30 crossovers, 2 of 828 on
    # XAUUSD and 0 of 894 on EURUSD. That is structural, not a data quirk — a
    # SuperTrend flip at sensitivity 4 already requires close to travel ~4x ATR,
    # which all but guarantees it sits on the correct side of a 13-bar mean. So
    # the indicator's "SuperTrend + SMA confirmation" is, in practice, just
    # SuperTrend. Raise this materially (or drop sensitivity) before expecting
    # it to filter anything.
    trend_sma_length: int = 13

    # ── Signal-strength MAs (diagnostic only) ─────────────────────────────────
    # These pick the "Buy" vs "Strong Buy" label text and gate nothing. Recorded
    # on each Trade so the distinction can be backtested as a filter later.
    fast_sma_length: int = 8
    slow_sma_length: int = 9
    # Reproduce the source's inverted labelling (SMA8 >= SMA9 prints the WEAKER
    # "Buy"). True = bug-compatible with the chart; False = the sane reading.
    legacy_strength_labels: bool = True

    # ── Risk ──────────────────────────────────────────────────────────────────
    # Stop = signal bar's low - ATR(risk_atr_length) * multiplier  (long)
    #        signal bar's high + ATR(risk_atr_length) * multiplier (short)
    risk_atr_length: int = 14
    atr_risk_multiplier: float = 1.0
    # Which of the indicator's 1:1 / 2:1 / 3:1 rungs to actually trade.
    # Ignored when `split_targets` is True.
    rr: float = 2.0

    # ── Split profit targets ──────────────────────────────────────────────────
    # When True the position is split in two: `tp1_fraction` of it closes at
    # `tp1_rr`, the remainder runs to `tp2_rr`. Overrides `rr`.
    #
    # Note this moves MB off the configuration its evidence was measured at
    # (rr 2.0, PF 1.215 median across 12 instruments — see README.md). 3R/4R
    # is past the furthest rung the source indicator even draws, so the
    # indicator's own chart offers no support for it either. Set False to
    # return to the measured baseline.
    split_targets: bool = True
    tp1_rr: float = 3.0
    tp2_rr: float = 4.0
    tp1_fraction: float = 0.5
    # Skip signals whose ATR-derived stop is implausibly tight. 0 disables.
    # Left at 0 by default: the stop is already volatility-scaled, so unlike
    # Silver Bullet / Trendline this strategy needs no per-symbol point floor.
    min_risk_points: float = 0.0

    # ── Trade management ──────────────────────────────────────────────────────
    # Both off by default — the indicator has no trade management whatsoever,
    # so the honest baseline is a flat stop-or-target ride.
    breakeven_r: float = 0.0   # move stop to entry after this many R in profit
    trail_r: float = 0.0       # after breakeven, trail this many R behind best price
    # Close an open trade when the opposite signal fires. Not in the indicator
    # (it only ever draws labels), but the natural way to trade a flip system.
    exit_on_opposite_signal: bool = False

    # ── Discipline ────────────────────────────────────────────────────────────
    # Reuses silver_bullet.news_calendar (generic, not ICT-specific). Off by
    # default to keep the baseline run a pure read of the indicator.
    skip_news_days: bool = False

    # ── Diagnostics ───────────────────────────────────────────────────────────
    # Drives the indicator's 61-tier bar colouring. Purely visual there; kept
    # so each signal can record the RSI it fired at.
    rsi_length: int = 14
