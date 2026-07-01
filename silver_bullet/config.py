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
    # Default ICT Silver Bullet windows for US30: NY 10:00–11:00 and 11:00–12:00.
    windows: List[Tuple[str, str]] = field(
        default_factory=lambda: [("10:00", "11:00"), ("11:00", "12:00")]
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
    stop_buffer_points: float = 0.5

    # ── Profit target ─────────────────────────────────────────────────────────
    # "rr"               : fixed risk-to-reward ratio
    # "opposite_liquidity": nearest confirmed swing on the other side
    target_mode: str = "opposite_liquidity"
    rr: float = 2.0

    # ── Off-hours trading ─────────────────────────────────────────────────────
    # Scan for setups outside the defined session windows.
    # Each clock-hour becomes its own synthetic window (fresh sweep+FVG state).
    # Positions are force-closed at off_hours_close_time instead of window end.
    use_market_order: bool = False   # enter at market on signal; skip limit/retrace wait
    sweep_entry_mode: bool = False   # enter on sweep alone, no FVG required (test/demo only)
    off_hours_trading: bool = False
    off_hours_max_trades: int = 3        # fills allowed per calendar day
    off_hours_close_time: str = "17:00"  # ET — force-close before this hour

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
    # Default off — large news-day moves are caught by the extended news_rr target.
    skip_news_days: bool = False
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
    breakeven_r: float = 0.5
    # After breakeven triggers, trail stop this many R behind the best price.
    # e.g. 1.0 → stop stays 1R below the highest high seen (long).
    # Set to 0.0 to disable trailing entirely.
    trail_r: float = 0.25
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
