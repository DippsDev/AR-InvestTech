"""All strategy tunables in one place. Change here; nowhere else.

Unlike SilverBulletConfig's defaults (tuned against 3 years of US30 M5
history), these numbers are reasoned starting points, not backtested —
there is no historical US30 H1 run through this logic yet. Validate on
a demo account (or a future trendline/backtest.py harness) before relying
on them.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TrendlineConfig:
    # ── Instrument ────────────────────────────────────────────────────────────
    # Informational only — bot.py always overrides the live adapter's actual
    # symbol with whatever US30 ticker Silver Bullet resolved on this broker,
    # so both strategies trade the identical instrument.
    symbol: str = "US30"
    bars_lookback: int = 300   # H1 bars fetched per cycle (~12.5 days of near-continuous data)

    # ── Swing detection ───────────────────────────────────────────────────────
    # Bars required on each side of a pivot to confirm it as a swing point.
    swing_lookback: int = 3

    # ── Trendline construction ────────────────────────────────────────────────
    # Bars used for the rolling average bar-range that steepness is judged against.
    avg_range_lookback: int = 20
    # Reject a candidate line if |slope per bar| > this * avg_bar_range.
    # The source material's own guidance: gently-sloping trendlines are strong
    # and reliable; steep ones are weak and rarely obeyed more than once.
    steepness_max_ratio: float = 1.0
    # Wiggle room (in points) allowed for bars strictly between the two anchor
    # points before the line is rejected as "drawn through an obstruction".
    obstruction_tolerance_points: float = 3.0

    # ── Trendline invalidation / touch ────────────────────────────────────────
    # A bar CLOSING beyond the line by more than this retires it; closing
    # beyond it by less is treated as a temporary breach (line stays active).
    breach_tolerance_points: float = 5.0
    # How close price must come to the line's current value to count as a touch.
    touch_tolerance_points: float = 3.0

    # ── Candlestick confirmation ──────────────────────────────────────────────
    candle_body_ratio_max: float = 0.30    # doji/hammer/spinning-top body-vs-range ceiling
    candle_wick_ratio_min: float = 2.0     # hammer/shooting-star wick-vs-body floor
    railway_length_ratio_min: float = 1.5  # railway-track body-vs-avg-body floor
    avg_body_lookback: int = 20

    # ── Stop loss ─────────────────────────────────────────────────────────────
    # Extra distance beyond the touching candle's extreme for the initial stop.
    stop_buffer_points: float = 5.0
    # Minimum risk in points; signals with a smaller stop distance are skipped.
    min_risk_points: float = 15.0

    # ── Profit target ─────────────────────────────────────────────────────────
    # "opposite_swing" : nearest confirmed swing on the other side, if it clears
    #                    min_rr_for_swing_target; else falls back to "rr".
    # "rr"             : fixed risk-to-reward ratio.
    target_mode: str = "opposite_swing"
    rr: float = 3.0   # the document's own stated R:R floor ("always R:R above 1:3")
    min_rr_for_swing_target: float = 3.0

    # ── Split profit targets ──────────────────────────────────────────────────
    # When True the position is split in two: `tp1_fraction` of it closes at
    # `tp1_rr`, the remainder runs to `tp2_rr`. Both halves share one stop, so
    # breakeven/trailing continue to move the survivor's stop after TP1 fills.
    #
    # Setting this True overrides `target_mode` — the opposite-swing lookup is
    # skipped and both targets are pure R multiples. Set False to go back to a
    # single target chosen by `target_mode`.
    split_targets: bool = True
    tp1_rr: float = 3.0
    tp2_rr: float = 4.0
    tp1_fraction: float = 0.5   # portion of the position closed at TP1

    # ── Trade management ──────────────────────────────────────────────────────
    # Move stop to entry once price travels this many R in our favour.
    breakeven_r: float = 1.0
    # After breakeven triggers, trail stop this many R behind the best price.
    trail_r: float = 0.5

    # ── Discipline ────────────────────────────────────────────────────────────
    # No session windows (US30 trades near-continuously like Silver Bullet's
    # own off-hours mode). Concurrent positions are allowed by default — the
    # live adapter tracks each open position independently by ticket, and
    # TL_MAX_TRADES_PER_DAY is the only throttle on how many entries happen
    # in a day. Set True to go back to a single open/pending position at a time.
    one_trade_at_a_time: bool = False
    # Skip new entries on high-impact US macro news days (reuses
    # silver_bullet.news_calendar.is_news_day — that calendar is generic,
    # not Silver-Bullet-specific).
    skip_news_days: bool = True
    # v1 is aggressive-entry-only; kept as a field so a future conservative
    # (pending-order) mode is a config flip, not a rewrite.
    use_market_order: bool = True
