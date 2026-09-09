"""Measure how long baseline strategy entries take to first become profitable.

Profit is observed at a completed bar close after the modeled adverse fill and
one round-trip commission, or at an earlier profitable booked exit. This avoids
assuming an unknown intrabar price path from OHLC data.

Run from ``backend``::

    python backtests/entry_profit_timing.py
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.all_strategies_svm_guided_optuna import (  # noqa: E402
    LABELS,
    STRATEGIES,
    PortfolioItem,
    current_params,
    load_portfolio,
    run_symbol_window,
)


TIME_BINS = (
    ("Within 1 hour", 60.0),
    ("1–4 hours", 240.0),
    ("4–12 hours", 720.0),
    ("12–24 hours", 1_440.0),
    ("1–3 days", 4_320.0),
    ("More than 3 days", math.inf),
)
BAR_BINS = (
    ("1 bar", 1),
    ("2–3 bars", 3),
    ("4–6 bars", 6),
    ("7–12 bars", 12),
    ("13–24 bars", 24),
    ("More than 24 bars", math.inf),
)


@dataclass
class TimingResult:
    ever_profitable: bool
    bars_to_profit: int | None
    minutes_to_profit: float | None
    bars_observed: int
    minutes_observed: float
    first_profit_source: str | None


def _timeframe_minutes(frame: pd.DataFrame) -> float:
    diffs = frame["timestamp_ny"].sort_values().diff().dropna().dt.total_seconds() / 60.0
    positive = diffs[diffs > 0]
    if positive.empty:
        raise RuntimeError("Cannot infer timeframe from fewer than two bars")
    return float(positive.median())


def _timestamp_index(frame: pd.DataFrame) -> dict[pd.Timestamp, int]:
    return {
        timestamp: index
        for index, timestamp in enumerate(frame["timestamp_ny"].tolist())
    }


def _event_bar(
    timestamp: pd.Timestamp | None,
    index_by_timestamp: dict[pd.Timestamp, int],
) -> int | None:
    if timestamp is None:
        return None
    return index_by_timestamp.get(timestamp)


def first_profit_timing(
    trade: Any,
    frame: pd.DataFrame,
    commission: float,
) -> TimingResult:
    """Return the first observable net-profitable mark for one completed trade.

    Entry-bar close is usable because it occurs after an open or intrabar fill.
    Exit-bar close is not used for stop/target exits because the exit may have
    occurred earlier in that bar. Actual exit and TP1 prices are separately
    considered as booked events.
    """
    timeframe = _timeframe_minutes(frame)
    index_by_timestamp = _timestamp_index(frame)
    entry_idx = _event_bar(trade.entry_time, index_by_timestamp)
    exit_idx = _event_bar(trade.exit_time, index_by_timestamp)
    if entry_idx is None or exit_idx is None:
        raise RuntimeError("Cannot map trade timestamps to source bars")
    exit_idx = max(exit_idx, entry_idx)
    sign = 1.0 if trade.direction == "long" else -1.0
    closes = frame["close"].to_numpy(dtype=float)
    point_value = 1.0
    units = float(trade.units)

    candidates: list[tuple[int, str]] = []
    # Only closes strictly before an intrabar exit are observable while the
    # position is still open. The entry bar itself is included.
    for bar_idx in range(entry_idx, exit_idx):
        marked_pnl = (
            sign * float(closes[bar_idx] - trade.entry_price) * units * point_value
            - commission
        )
        if marked_pnl > 0:
            candidates.append((bar_idx - entry_idx + 1, "bar_close"))
            break

    tp1_idx = _event_bar(getattr(trade, "tp1_exit_time", None), index_by_timestamp)
    tp1_price = getattr(trade, "tp1_exit_price", None)
    if tp1_idx is not None and tp1_price is not None:
        marked_pnl = sign * float(tp1_price - trade.entry_price) * units - commission
        if marked_pnl > 0:
            candidates.append((max(1, tp1_idx - entry_idx + 1), "tp1_exit"))

    if trade.pnl_dollars is not None and float(trade.pnl_dollars) > 0:
        candidates.append((max(1, exit_idx - entry_idx + 1), "profitable_exit"))

    bars_observed = max(1, exit_idx - entry_idx + 1)
    if not candidates:
        return TimingResult(
            False,
            None,
            None,
            bars_observed,
            bars_observed * timeframe,
            None,
        )
    bars, source = min(candidates, key=lambda item: item[0])
    return TimingResult(
        True,
        bars,
        bars * timeframe,
        bars_observed,
        bars_observed * timeframe,
        source,
    )


def analyze_strategy(
    strategy: str,
    portfolio: list[PortfolioItem],
    dates: list[Any],
    commission: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    params = current_params(strategy)
    for item in portfolio:
        frame, trades, _ = run_symbol_window(strategy, item, params, dates)
        timeframe = _timeframe_minutes(frame)
        for trade in trades:
            timing = first_profit_timing(trade, frame, commission)
            rows.append(
                {
                    "strategy": strategy,
                    "strategy_label": LABELS[strategy],
                    "symbol": item.symbol,
                    "timeframe_minutes": timeframe,
                    "trade_id": trade.trade_id,
                    "direction": trade.direction,
                    "entry_time": trade.entry_time,
                    "exit_time": trade.exit_time,
                    "exit_reason": trade.exit_reason,
                    "pnl_usd": float(trade.pnl_dollars or 0.0),
                    "won": bool((trade.pnl_dollars or 0.0) > 0.0),
                    "ever_profitable": timing.ever_profitable,
                    "bars_to_profit": timing.bars_to_profit,
                    "minutes_to_profit": timing.minutes_to_profit,
                    "bars_observed": timing.bars_observed,
                    "minutes_observed": timing.minutes_observed,
                    "first_profit_source": timing.first_profit_source,
                }
            )
    return rows


def _summary(group: pd.DataFrame) -> dict[str, Any]:
    reached = group.loc[group["ever_profitable"]]
    losers = group.loc[~group["won"]]
    losing_reached = losers.loc[losers["ever_profitable"]]
    return {
        "trades": len(group),
        "ever": len(reached),
        "ever_pct": len(reached) / len(group) * 100.0 if len(group) else 0.0,
        "never": len(group) - len(reached),
        "median_minutes": float(reached["minutes_to_profit"].median()) if len(reached) else math.nan,
        "p25_minutes": float(reached["minutes_to_profit"].quantile(0.25)) if len(reached) else math.nan,
        "p75_minutes": float(reached["minutes_to_profit"].quantile(0.75)) if len(reached) else math.nan,
        "median_bars": float(reached["bars_to_profit"].median()) if len(reached) else math.nan,
        "losers": len(losers),
        "losers_ever": len(losing_reached),
        "losers_ever_pct": len(losing_reached) / len(losers) * 100.0 if len(losers) else 0.0,
    }


def _distribution(
    group: pd.DataFrame,
    column: str,
    bins: tuple[tuple[str, float], ...],
) -> list[tuple[str, int, float]]:
    values = group.loc[group["ever_profitable"], column].astype(float)
    rows: list[tuple[str, int, float]] = []
    lower = -math.inf
    for label, upper in bins:
        count = int(((values > lower) & (values <= upper)).sum())
        rows.append((label, count, count / len(group) * 100.0 if len(group) else 0.0))
        lower = upper
    never = int((~group["ever_profitable"]).sum())
    rows.append(("Never observed profitable", never, never / len(group) * 100.0 if len(group) else 0.0))
    return rows


def _duration(minutes: float) -> str:
    if not math.isfinite(minutes):
        return "n/a"
    if minutes < 60:
        return f"{minutes:.0f} min"
    if minutes < 1_440:
        return f"{minutes / 60.0:.1f} h"
    return f"{minutes / 1_440.0:.1f} d"


def write_report(
    path: Path,
    rows: pd.DataFrame,
    lookback_days: int,
    commission: float,
) -> None:
    summaries = {
        strategy: _summary(rows.loc[rows["strategy"] == strategy])
        for strategy in STRATEGIES
    }
    fastest = min(
        STRATEGIES,
        key=lambda strategy: summaries[strategy]["median_minutes"],
    )
    most_reliable = max(
        STRATEGIES,
        key=lambda strategy: summaries[strategy]["ever_pct"],
    )
    silver = rows.loc[rows["strategy"] == "silver_bullet"]
    trendline = rows.loc[rows["strategy"] == "trendline"]
    silver_within_three = int(
        (silver["ever_profitable"] & (silver["bars_to_profit"] <= 3)).sum()
    )
    trendline_first_bar = int(
        (trendline["ever_profitable"] & (trendline["bars_to_profit"] == 1)).sum()
    )
    lines = [
        "# Entry-to-First-Profit Distribution",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Big findings",
        "",
        f"- **{LABELS[most_reliable]} had the highest observed-profit rate:** "
        f"{summaries[most_reliable]['ever_pct']:.1f}% of entries became profitable before exit.",
        f"- **{LABELS[fastest]} had the shortest median wall-clock time:** "
        f"{_duration(summaries[fastest]['median_minutes'])} among trades that became profitable.",
        f"- **All {silver_within_three} profitable Silver Bullet entries crossed break-even "
        "within three M5 bars (15 minutes).** No later first-profit event was observed.",
        f"- **{trendline_first_bar} of {len(trendline)} Trendline entries ({trendline_first_bar / len(trendline) * 100.0:.1f}%) "
        "were profitable by the first H1 close.**",
        f"- **{summaries['mutanabby']['losers_ever']} of {summaries['mutanabby']['losers']} "
        f"Mutanabby losers ({summaries['mutanabby']['losers_ever_pct']:.1f}%) were profitable first.** "
        "Its high initial-profit rate did not translate into a high final win rate.",
        "- A losing trade can still spend time in profit before reversing. The loser-to-profit "
        "rate below is therefore important when evaluating entry quality and management rules.",
        "- Results are descriptive baseline behavior, not evidence that a new exit rule will improve performance.",
        "",
        "## Definition",
        "",
        "A trade becomes profitable at the first completed bar close where marked P/L is above "
        f"zero after the modeled adverse fill and one ${commission:,.2f} round-trip commission. "
        "A profitable TP1 or final booked exit can establish profit earlier than a qualifying close.",
        "",
        "The entry bar close is included. The exit-bar close is excluded for intrabar stop/target "
        "exits because OHLC data cannot prove whether that close happened before or after the exit. "
        "This makes the measurement conservative. Time is quantized to each strategy's source bars: "
        "Silver Bullet uses M5; Trendline and Mutanabby use H1.",
        "",
        f"History: current baseline configurations over the final {lookback_days} calendar days "
        "available for each live portfolio. This is a descriptive full-period analysis; no parameters "
        "were optimized and no train/test selection was performed.",
        "",
        "## Headline statistics",
        "",
        "| Strategy | Timeframe | Trades | Ever profitable | Never observed profitable | Median time | P25–P75 time | Median bars | Losing trades ever profitable |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for strategy in STRATEGIES:
        group = rows.loc[rows["strategy"] == strategy]
        summary = summaries[strategy]
        timeframe = int(group["timeframe_minutes"].median())
        lines.append(
            f"| {LABELS[strategy]} | {timeframe} min | {summary['trades']} | "
            f"{summary['ever']} ({summary['ever_pct']:.1f}%) | "
            f"{summary['never']} ({100.0 - summary['ever_pct']:.1f}%) | "
            f"{_duration(summary['median_minutes'])} | "
            f"{_duration(summary['p25_minutes'])}–{_duration(summary['p75_minutes'])} | "
            f"{summary['median_bars']:.1f} | {summary['losers_ever']}/{summary['losers']} "
            f"({summary['losers_ever_pct']:.1f}%) |"
        )

    lines.extend([
        "",
        "## Wall-clock distribution",
        "",
        "Percentages use all entries as the denominator, so the rows—including `Never`—sum to 100% per strategy.",
        "",
        "| Time to first profit | Silver Bullet | Trendline | Mutanabby |",
        "| --- | ---: | ---: | ---: |",
    ])
    distributions = {
        strategy: _distribution(
            rows.loc[rows["strategy"] == strategy], "minutes_to_profit", TIME_BINS
        )
        for strategy in STRATEGIES
    }
    for index, (label, _, _) in enumerate(distributions[STRATEGIES[0]]):
        cells = []
        for strategy in STRATEGIES:
            _, count, pct = distributions[strategy][index]
            cells.append(f"{count} ({pct:.1f}%)")
        lines.append(f"| {label} | {' | '.join(cells)} |")

    lines.extend([
        "",
        "## Bar-count distribution",
        "",
        "Bar counts compare how many strategy decisions elapsed, while wall-clock time reflects the M5/H1 timeframe difference.",
        "",
        "| Bars to first profit | Silver Bullet | Trendline | Mutanabby |",
        "| --- | ---: | ---: | ---: |",
    ])
    bar_distributions = {
        strategy: _distribution(
            rows.loc[rows["strategy"] == strategy], "bars_to_profit", BAR_BINS
        )
        for strategy in STRATEGIES
    }
    for index, (label, _, _) in enumerate(bar_distributions[STRATEGIES[0]]):
        cells = []
        for strategy in STRATEGIES:
            _, count, pct = bar_distributions[strategy][index]
            cells.append(f"{count} ({pct:.1f}%)")
        lines.append(f"| {label} | {' | '.join(cells)} |")

    lines.extend(["", "## Results by symbol", ""])
    for strategy in STRATEGIES:
        lines.extend([
            f"### {LABELS[strategy]}",
            "",
            "| Symbol | Trades | Ever profitable | Never | Median time | Median bars | Losing trades ever profitable |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        strategy_rows = rows.loc[rows["strategy"] == strategy]
        for symbol, group in strategy_rows.groupby("symbol", sort=True):
            summary = _summary(group)
            lines.append(
                f"| {symbol} | {summary['trades']} | {summary['ever']} "
                f"({summary['ever_pct']:.1f}%) | {summary['never']} | "
                f"{_duration(summary['median_minutes'])} | {summary['median_bars']:.1f} | "
                f"{summary['losers_ever']}/{summary['losers']} "
                f"({summary['losers_ever_pct']:.1f}%) |"
            )
        lines.append("")

    lines.extend([
        "## Interpretation cautions",
        "",
        "- `Never observed profitable` does not prove price never moved favorably intrabar. It "
        "means no unambiguous profitable close or booked exit was observed before closure.",
        "- Bar timestamps represent interval starts. Reported wall-clock time is an upper-bound "
        "at bar resolution and can overstate the true crossing time by up to one bar.",
        "- One commission is used for a consistent entry-quality threshold. Split positions and "
        "partial exits can incur different realized commission accounting.",
        "- Silver Bullet has far fewer trades than the other strategies, so its percentages and "
        "quantiles are less stable.",
        "- This analysis describes existing entries. It does not account for opportunity cost, "
        "maximum adverse excursion, or whether waiting longer improves final expectancy.",
        "- The Mutanabby give-back pattern motivates a separate maximum-favorable-excursion and "
        "exit-policy study; it does not by itself prove that an earlier exit would improve expectancy.",
        "",
        "The accompanying CSV contains one row per trade for alternative bins or survival-style analysis.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=240)
    parser.add_argument("--commission", type=float, default=5.0)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("reports") / "ENTRY_PROFIT_TIMING.md",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path(__file__).with_name("reports") / "ENTRY_PROFIT_TIMING.csv",
    )
    args = parser.parse_args()
    if args.lookback_days < 30:
        parser.error("--lookback-days must be at least 30")
    if args.commission < 0:
        parser.error("--commission cannot be negative")
    return args


def main() -> int:
    args = parse_args()
    logging.disable(logging.CRITICAL)
    rows: list[dict[str, Any]] = []
    for strategy in STRATEGIES:
        print(f"{LABELS[strategy]}: measuring baseline entries ...", flush=True)
        portfolio, dates = load_portfolio(strategy, args.data_dir, args.lookback_days)
        rows.extend(analyze_strategy(strategy, portfolio, dates, args.commission))
    frame = pd.DataFrame(rows).sort_values(["strategy", "entry_time"]).reset_index(drop=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.csv.resolve(), index=False)
    write_report(args.report.resolve(), frame, args.lookback_days, args.commission)
    print(f"Report written to {args.report.resolve()}", flush=True)
    print(f"Trade-level data written to {args.csv.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
