"""All strategy tunables in one place. Change here; nowhere else."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class SilverBulletConfig:
    # ── Instrument ────────────────────────────────────────────────────────────
    symbol: str = "US30"
    timeframe_minutes: int = 5

    # ── Session windows (America/New_York) ────────────────────────────────────
    # List of ("HH:MM", "HH:MM") open/close pairs.  DST handled automatically.
    # The two core ICT Silver Bullet windows (NY 10:00–11:00, 11:00–12:00) plus
    # the early-afternoon 13:30–14:30 window.
    #
    # The third window is not an extra: every run in the 180-day selection
    # campaign that chose DE30m/EURUSDm/GBPUSDm used all three (see the
    # `windows` key in backtests/multi_sb_*.json), so a 2-window default meant
    # live traded a narrower configuration than the one its symbols were
    # validated on. Re-measured over the same 180 days with each symbol's own
    # campaign costs, the third window is strictly better on all three —
    # more trades AND a higher profit factor, not a frequency-for-edge trade:
    #
    #     DE30m    16 trades PF 5.84  ->  20 trades PF 6.16
    #     EURUSDm  12 trades PF 3.46  ->  17 trades PF 5.50
    #     GBPUSDm  15 trades PF 2.44  ->  17 trades PF 3.63
    #
    # Adding the London pair (03:00–05:00) on top more than doubles trades
    # again but costs DE30m most of its edge (PF 6.16 -> 1.75), so it stays
    # behind the SB_AGGRESSIVE flag rather than becoming the default.
    windows: List[Tuple[str, str]] = field(
        default_factory=lambda: [("10:00", "11:00"), ("11:00", "12:00"), ("13:30", "14:30")]
    )

    # ── Swing detection ───────────────────────────────────────────────────────
    # Bars required on each side of a pivot to confirm it as a swing point.
    swing_lookback: int = 3
    # How many bars back to scan for sweep-eligible confirmed swings.
    sweep_lookback: int = 10

    # ── FVG filter ────────────────────────────────────────────────────────────
    # Minimum size of a fair-value gap (in index points) to qualify as a setup.
    # Grid search on 3-year US30 data showed 14.0 points produces the best
    # profit factor (2.31) while still keeping reasonable trade frequency.
    fvg_min_points: float = 14.0

    # ── Entry placement within FVG ────────────────────────────────────────────
    # "near_edge" : first edge price touches on retrace (conservative fill rate)
    # "mid"       : midpoint of the gap
    # "far_edge"  : deepest edge of the gap
    # Backtests on 3-year US30 data show "mid" performs best with the default
    # NY 10:00-12:00 windows and active breakeven/trailing stop.
    entry_in_fvg: str = "mid"

    # ── Stop loss ─────────────────────────────────────────────────────────────
    # Extra distance beyond the swept extreme for the initial stop.  Grid search
    # on 3-year US30 data showed 0.5 points produces a slightly better profit
    # factor (2.38) than the more common 1.0-point buffer (2.31).
    stop_buffer_points: float = 1.5

    # ── Profit target ─────────────────────────────────────────────────────────
    # "rr"               : fixed risk-to-reward ratio
    # "opposite_liquidity": nearest confirmed swing on the other side
    #
    # Note that, unlike trendline/config.py's min_rr_for_swing_target, there is
    # deliberately NO minimum reward:risk floor on the liquidity target here —
    # see _compute_target in strategy.py for the measurements behind that.
    target_mode: str = "opposite_liquidity"
    rr: float = 2.0

    # ── Split profit targets ──────────────────────────────────────────────────
    # When True the position is split in two: `tp1_fraction` of it closes at
    # `tp1_rr`, the remainder runs to `tp2_rr`. Overrides `target_mode`.
    #
    # ⚠ This is the reward floor the note above says not to add. Enabling it
    # replaces the nearest-liquidity target with a 3R floor, and that target is
    # where Silver Bullet's edge lives: measured over the full ~17-month M5
    # history for all three live symbols, a floor of 0.50R and above took the
    # strategy from +$4,820 net / ~62% win rate to +$118 / ~46%. The trade
    # count does not change — a floor does not filter setups, it relocates the
    # target past where these fast scalps actually reverse.
    #
    # Enabled here at explicit request. Set False to restore the measured
    # behaviour; that is the single highest-value revert in this config.
    split_targets: bool = True
    tp1_rr: float = 3.0
    tp2_rr: float = 4.0
    tp1_fraction: float = 0.5

    # ── Off-hours trading ─────────────────────────────────────────────────────
    # Scan for setups outside the defined session windows.
    # Each clock-hour becomes its own synthetic window (fresh sweep+FVG state).
    # Positions are force-closed at off_hours_close_time instead of window end.
    use_market_order: bool = False   # enter at market on signal; skip limit/retrace wait
    sweep_entry_mode: bool = False   # enter on sweep alone, no FVG required (test/demo only)
    off_hours_trading: bool = False
    off_hours_max_trades: int = 5        # fills allowed per calendar day
    off_hours_close_time: str = "17:00"  # ET — force-close before this hour

    # ── Off-hours scalp mode (Option 1) ───────────────────────────────────────
    # These values override the normal Silver Bullet parameters for any trade
    # placed outside the configured NY session windows. They are designed for
    # low-volatility, small-target scalping while the main session is closed.
    # Tuned on us30_m5_200d.csv for best balance (PNL/DD × profit factor).
    off_hours_fvg_min_points: float = 12.0
    off_hours_min_risk_points: float = 3.0
    off_hours_target_mode: str = "rr"
    off_hours_rr: float = 2.5
    off_hours_breakeven_r: float = 0.25
    off_hours_trail_r: float = 0.1
    off_hours_early_exit_r: float = 0.5
    off_hours_deep_profit_r: float = 2.0
    off_hours_deep_trail_r: float = 0.2

    # ── Trade management ──────────────────────────────────────────────────────
    one_trade_per_window: bool = True
    # Minimum risk in points; signals with smaller risk are skipped.
    # Default equals stop_buffer_points so the FVG must provide at least
    # that much separation from the stop.
    min_risk_points: float = 5.0
    # Filter signals to match the previous trading day's candle direction:
    # yesterday bullish → only longs today; yesterday bearish → only shorts today.
    # Uses the prior day's completed candle, zero lookahead.
    # Off by default for Silver Bullet: it is a reversal strategy, so
    # counter-trend days (yesterday bearish, today bullish SB setup) are often
    # the strongest setups. Use --use-daily-bias only with trend-following overlays.
    use_daily_bias: bool = False
    # Skip news days entirely (NFP / FOMC / CPI / GDP).
    # Default on — the live bot will not open new trades on high-impact macro days.
    skip_news_days: bool = True
    # On high-impact news days (NFP/FOMC/CPI/GDP), use this R:R instead of `rr`.
    # Set to 0.0 to use the same target on all days.
    news_rr: float = 5.0
    # On news day trades, disable the trailing stop so the extended 5R target
    # has room to be reached without early trail exits.
    # False = keep the same trailing stop on news days (trail still locks in
    # intermediate profits; if price makes a clean 5R move the target is hit).
    news_disable_trail: bool = False

    # Move stop to entry once price travels this many R in our favour.
    # Set to 0.0 to disable breakeven entirely.
    # 0.25 chosen via grid search over data/us30_m5_current.csv (49 combos,
    # session-only, aggressive-mode filters): best profit factor (2.03) and
    # win rate (62.9%) in the whole grid — protecting gains early consistently
    # beat waiting, since these tight-filter setups are noisy/choppy.
    breakeven_r: float = 0.25
    # After breakeven triggers, trail stop this many R behind the best price.
    # e.g. 1.0 → stop stays 1R below the highest high seen (long).
    # Set to 0.0 to disable trailing entirely. 0.1 likewise won the same grid search.
    trail_r: float = 0.1
    # Early exit: if price moves this many R against us BEFORE breakeven triggers,
    # cut the trade immediately rather than waiting for the structural stop.
    # 0.0 = disabled.
    early_exit_r: float = 0.4
    # Deep-profit trail: once unrealised gain exceeds this R-multiple, compress
    # the trail to deep_trail_r (much tighter) to lock in the large win.
    deep_profit_r: float = 2.0
    deep_trail_r: float = 0.1

    # ── Costs (applied at fill) ───────────────────────────────────────────────
    spread_points: float = 2.0       # half-spread added to ask / subtracted from bid
    commission_per_trade: float = 5.0  # USD per round trip
    slippage_points: float = 1.0     # additional adverse slippage at fill

    # ── Position sizing ───────────────────────────────────────────────────────
    risk_per_trade: float = 100.0    # USD risked per trade (used to size position)
    point_value: float = 1.0         # USD per index point per unit sized
