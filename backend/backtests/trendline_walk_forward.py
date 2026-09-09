"""Walk-forward Optuna optimization for the live Trendline portfolio.

Each trial is scored on several chronological forward windows.  The first
part of the development history supplies the initial context, each following
window is scored in order, and the final holdout is evaluated exactly once
after parameter selection.

Run from ``backend``::

    python backtests/trendline_walk_forward.py --trials 40
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.optuna_sharpe import (  # noqa: E402
    SYMBOL_TO_FILE,
    TEST_WARMUP_BARS,
    _costs,
    _m5_scale,
    _sort_trades,
    _trendline_config,
    daily_pnl_sharpe,
)
from multi_symbol_targets import TL_TARGETS  # noqa: E402
from silver_bullet.metrics import compute_metrics  # noqa: E402
from trendline.backtest import BacktestCosts, run_backtest  # noqa: E402
from trendline.data import prepare_from_m5  # noqa: E402


@dataclass
class PreparedSymbol:
    symbol: str
    scale: float
    frame: pd.DataFrame


@dataclass
class Fold:
    number: int
    train_dates: list[date]
    validation_dates: list[date]


@dataclass
class WindowResult:
    sharpe: float
    metrics: dict[str, Any]
    per_symbol: dict[str, dict[str, Any]]
    trades: list[Any]
    dates: list[date]


def load_portfolio(
    data_dir: Path,
    lookback_days: int,
) -> tuple[list[PreparedSymbol], list[date]]:
    prepared: list[PreparedSymbol] = []
    first_dates: list[date] = []
    last_dates: list[date] = []
    all_dates: set[date] = set()

    for symbol in TL_TARGETS:
        path = data_dir / SYMBOL_TO_FILE[symbol]
        if not path.exists():
            raise FileNotFoundError(f"Missing data for {symbol}: {path}")
        frame = prepare_from_m5(path)
        dates = frame["timestamp_ny"].dt.date
        prepared.append(PreparedSymbol(symbol, _m5_scale(path), frame))
        first_dates.append(dates.iloc[0])
        last_dates.append(dates.iloc[-1])
        all_dates.update(dates.tolist())

    common_start = max(first_dates)
    common_end = min(last_dates)
    requested_start = (
        pd.Timestamp(common_end) - pd.Timedelta(days=lookback_days - 1)
    ).date()
    evaluation_start = max(common_start, requested_start)
    ordered_dates = sorted(
        day for day in all_dates if evaluation_start <= day <= common_end
    )
    if len(ordered_dates) < 20:
        raise ValueError("Not enough common history to build walk-forward folds")
    return prepared, ordered_dates


def make_folds(
    dates: list[date],
    holdout_fraction: float,
    folds: int,
    initial_train_fraction: float,
) -> tuple[list[Fold], list[date], list[date]]:
    development_end = min(
        max(int(len(dates) * (1.0 - holdout_fraction)), 2),
        len(dates) - 1,
    )
    development = dates[:development_end]
    holdout = dates[development_end:]
    max_initial_end = len(development) - folds
    if max_initial_end < 1:
        raise ValueError("Not enough development dates for the requested fold count")
    initial_end = min(
        max(int(len(development) * initial_train_fraction), 1),
        max_initial_end,
    )
    forward_dates = development[initial_end:]
    blocks = [list(block) for block in np.array_split(forward_dates, folds) if len(block)]
    result: list[Fold] = []
    consumed = initial_end
    for number, block in enumerate(blocks, 1):
        result.append(Fold(number, development[:consumed], block))
        consumed += len(block)
    return result, development, holdout


def evaluate_window(
    portfolio: list[PreparedSymbol],
    params: dict[str, Any],
    dates: list[date],
) -> WindowResult:
    wanted = set(dates)
    all_trades: list[Any] = []
    per_symbol: dict[str, dict[str, Any]] = {}

    for item in portfolio:
        frame_dates = item.frame["timestamp_ny"].dt.date
        positions = np.flatnonzero(frame_dates.isin(wanted).to_numpy())
        if not len(positions):
            per_symbol[item.symbol] = compute_metrics([])
            per_symbol[item.symbol]["sharpe"] = 0.0
            continue

        warmup_start = max(0, int(positions[0]) - TEST_WARMUP_BARS)
        stop = int(positions[-1]) + 1
        frame = item.frame.iloc[warmup_start:stop].reset_index(drop=True)
        config = _trendline_config(item, params)
        trades = run_backtest(frame, config, _costs(BacktestCosts, item.scale))
        trades = [trade for trade in trades if trade.entry_time.date() in wanted]
        trades = _sort_trades(trades)
        symbol_dates = sorted(set(frame_dates.iloc[positions].tolist()))
        metrics = compute_metrics(trades)
        metrics["sharpe"] = daily_pnl_sharpe(trades, symbol_dates)
        per_symbol[item.symbol] = metrics
        all_trades.extend(trades)

    all_trades = _sort_trades(all_trades)
    return WindowResult(
        sharpe=daily_pnl_sharpe(all_trades, dates),
        metrics=compute_metrics(all_trades),
        per_symbol=per_symbol,
        trades=all_trades,
        dates=dates,
    )


def suggest_params(trial: optuna.Trial) -> dict[str, Any]:
    """A deliberately compact search space around the current configuration."""
    breakeven_r = trial.suggest_categorical("breakeven_r", [0.0, 0.5, 1.0, 1.5])
    return {
        "swing_lookback": trial.suggest_int("swing_lookback", 2, 5),
        "steepness_max_ratio": trial.suggest_float(
            "steepness_max_ratio", 0.5, 1.5, step=0.25
        ),
        "touch_scale": trial.suggest_float("touch_scale", 0.6, 1.5, log=True),
        "obstruction_scale": trial.suggest_float(
            "obstruction_scale", 0.6, 1.5, log=True
        ),
        "stop_buffer_scale": trial.suggest_float(
            "stop_buffer_scale", 0.7, 1.5, log=True
        ),
        "min_risk_scale": trial.suggest_float("min_risk_scale", 0.7, 1.5, log=True),
        "candle_body_ratio_max": trial.suggest_float(
            "candle_body_ratio_max", 0.20, 0.40
        ),
        "candle_wick_ratio_min": trial.suggest_float(
            "candle_wick_ratio_min", 1.5, 3.0
        ),
        "breakeven_r": breakeven_r,
        "trail_r": (
            trial.suggest_categorical("trail_r", [0.25, 0.5, 0.75, 1.0])
            if breakeven_r > 0
            else 0.0
        ),
    }


def baseline_params() -> dict[str, Any]:
    return {
        "swing_lookback": 3,
        "steepness_max_ratio": 1.0,
        "touch_scale": 1.0,
        "obstruction_scale": 1.0,
        "stop_buffer_scale": 1.0,
        "min_risk_scale": 1.0,
        "candle_body_ratio_max": 0.3,
        "candle_wick_ratio_min": 2.0,
        "breakeven_r": 1.0,
        "trail_r": 0.5,
    }


def pooled_result(results: list[WindowResult]) -> WindowResult:
    trades = _sort_trades([trade for result in results for trade in result.trades])
    dates = sorted({day for result in results for day in result.dates})
    per_symbol: dict[str, dict[str, Any]] = {}
    for symbol in results[0].per_symbol:
        # Trade has no symbol field, so aggregate the already-separated rows.
        per_symbol[symbol] = {
            "num_trades": sum(result.per_symbol[symbol]["num_trades"] for result in results),
            "net_pnl_usd": round(
                sum(result.per_symbol[symbol]["net_pnl_usd"] for result in results), 2
            ),
        }
    return WindowResult(
        sharpe=daily_pnl_sharpe(trades, dates),
        metrics=compute_metrics(trades),
        per_symbol=per_symbol,
        trades=trades,
        dates=dates,
    )


def optimize(
    portfolio: list[PreparedSymbol],
    folds: list[Fold],
    trials: int,
    seed: int,
    min_fold_trades: int,
    stability_penalty: float,
) -> tuple[optuna.Study, dict[str, Any], list[WindowResult]]:
    sampler = optuna.samplers.TPESampler(
        seed=seed, n_startup_trials=min(10, max(1, trials // 3))
    )
    study = optuna.create_study(
        direction="maximize", sampler=sampler, study_name="trendline_walk_forward"
    )
    study.enqueue_trial(baseline_params())
    results_by_trial: dict[int, list[WindowResult]] = {}

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(trial)
        results = [
            evaluate_window(portfolio, params, fold.validation_dates)
            for fold in folds
        ]
        results_by_trial[trial.number] = results
        sharpes = np.asarray([result.sharpe for result in results], dtype=float)
        trades = [result.metrics["num_trades"] for result in results]
        pooled = pooled_result(results)
        trial.set_user_attr(
            "fold_sharpes", [round(float(value), 6) for value in sharpes]
        )
        trial.set_user_attr("fold_trades", trades)
        trial.set_user_attr("pooled_sharpe", round(pooled.sharpe, 6))
        trial.set_user_attr("net_pnl_usd", pooled.metrics["net_pnl_usd"])
        if min(trades) < min_fold_trades:
            return -1_000.0 + sum(trades) / 10_000.0
        return float(pooled.sharpe - stability_penalty * np.std(sharpes, ddof=0))

    def progress(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        completed = trial.number + 1
        if completed == 1 or completed % 10 == 0 or completed == trials:
            print(
                f"  {completed}/{trials} trials; best stability-adjusted "
                f"Sharpe={study.best_value:.4f}",
                flush=True,
            )

    study.optimize(objective, n_trials=trials, callbacks=[progress], gc_after_trial=True)
    best_params = suggest_params(optuna.trial.FixedTrial(study.best_params))
    return study, best_params, results_by_trial[study.best_trial.number]


def _fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, str):
        return value
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{digits}f}"


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _result_row(label: str, result: WindowResult) -> str:
    metrics = result.metrics
    return (
        f"| {label} | {result.sharpe:.3f} | {metrics['num_trades']} | "
        f"${metrics['net_pnl_usd']:,.2f} | {_fmt(metrics['profit_factor'], 2)} | "
        f"${metrics['max_drawdown_usd']:,.2f} | {metrics['win_rate_pct']:.1f}% |"
    )


def write_report(
    path: Path,
    args: argparse.Namespace,
    portfolio: list[PreparedSymbol],
    folds: list[Fold],
    development: list[date],
    holdout_dates: list[date],
    study: optuna.Study,
    best_params: dict[str, Any],
    baseline_folds: list[WindowResult],
    optimized_folds: list[WindowResult],
    baseline_holdout: WindowResult,
    optimized_holdout: WindowResult,
    elapsed: float,
) -> None:
    baseline_pooled = pooled_result(baseline_folds)
    optimized_pooled = pooled_result(optimized_folds)
    holdout_improved = optimized_holdout.sharpe > baseline_holdout.sharpe
    recommendation = (
        "The candidate improved the untouched holdout, but should still be forward-tested "
        "before changing live parameters."
        if holdout_improved
        else "Retain the current parameters; the selected candidate did not improve the untouched holdout."
    )
    lines = [
        "# Trendline Walk-Forward Optimization Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Git commit: `{_git_commit()}`",
        "",
        "## Executive summary",
        "",
        f"Optuna walk-forward Sharpe: {_fmt(baseline_pooled.sharpe)} → "
        f"{_fmt(optimized_pooled.sharpe)}. Untouched holdout Sharpe: "
        f"{_fmt(baseline_holdout.sharpe)} → {_fmt(optimized_holdout.sharpe)}.",
        "",
        recommendation,
        "",
        "## Method",
        "",
        f"- Portfolio: {', '.join(item.symbol for item in portfolio)}.",
        f"- Data: final {args.lookback_days} calendar days available in the repository.",
        f"- Development/holdout split: {1.0 - args.holdout_fraction:.0%}/"
        f"{args.holdout_fraction:.0%}; the holdout was evaluated only after selection.",
        f"- Walk-forward structure: {len(folds)} expanding chronological folds; the first "
        f"{args.initial_train_fraction:.0%} of development history initializes the first fold.",
        "- Objective: pooled annualized daily-P/L Sharpe across forward windows minus "
        f"{args.stability_penalty:g} × the standard deviation of fold Sharpes.",
        f"- Sparse-trial guard: at least {args.min_fold_trades} trades in every forward window.",
        f"- Optimizer: Optuna TPE, {args.trials} trials, seed {args.seed}; the current "
        "configuration is always trial 0.",
        f"- Warmup: up to {TEST_WARMUP_BARS} bars before each scored window. Only entries "
        "inside that window count.",
        "- Costs: $5 round-trip commission; spread and slippage scale with each symbol's "
        "median M5 range; fixed $100 risk per trade.",
        "- Search scope: line geometry, touch/obstruction tolerance, stop/risk filters, "
        "candlestick confirmation, and breakeven/trailing. Split targets remain at the "
        "current 3R/4R settings to keep the search space controlled.",
        "",
        "## Partitions",
        "",
        f"Development: {development[0]} to {development[-1]} ({len(development)} dates).  ",
        f"Untouched holdout: {holdout_dates[0]} to {holdout_dates[-1]} "
        f"({len(holdout_dates)} dates).",
        "",
        "| Fold | Expanding history | Forward validation | Train dates | Validation dates |",
        "| ---: | --- | --- | ---: | ---: |",
    ]
    for fold in folds:
        lines.append(
            f"| {fold.number} | {fold.train_dates[0]} to {fold.train_dates[-1]} | "
            f"{fold.validation_dates[0]} to {fold.validation_dates[-1]} | "
            f"{len(fold.train_dates)} | {len(fold.validation_dates)} |"
        )

    lines.extend([
        "",
        "## Aggregate results",
        "",
        "| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        _result_row("Current / pooled walk-forward", baseline_pooled),
        _result_row("Optuna / pooled walk-forward", optimized_pooled),
        _result_row("Current / untouched holdout", baseline_holdout),
        _result_row("Optuna / untouched holdout", optimized_holdout),
        "",
        "## Fold results",
        "",
        "| Fold | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for fold, current, optimized in zip(folds, baseline_folds, optimized_folds):
        lines.append(
            f"| {fold.number} | {_fmt(current.sharpe)} | {_fmt(optimized.sharpe)} | "
            f"{current.metrics['num_trades']} | {optimized.metrics['num_trades']} | "
            f"${current.metrics['net_pnl_usd']:,.2f} | ${optimized.metrics['net_pnl_usd']:,.2f} |"
        )

    lines.extend([
        "",
        "## Holdout by symbol",
        "",
        "| Symbol | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for symbol in baseline_holdout.per_symbol:
        current = baseline_holdout.per_symbol[symbol]
        optimized = optimized_holdout.per_symbol[symbol]
        lines.append(
            f"| {symbol} | {_fmt(current['sharpe'])} | {_fmt(optimized['sharpe'])} | "
            f"{current['num_trades']} | {optimized['num_trades']} | "
            f"${current['net_pnl_usd']:,.2f} | ${optimized['net_pnl_usd']:,.2f} |"
        )

    lines.extend([
        "",
        "## Selected parameters",
        "",
        "```json",
        json.dumps(best_params, indent=2, sort_keys=True),
        "```",
        "",
        "## Top trials",
        "",
        "| Rank | Trial | Objective | Pooled Sharpe | Fold Sharpes | Fold trades | Net P/L |",
        "| ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ])
    complete = [
        trial
        for trial in study.trials
        if trial.state == optuna.trial.TrialState.COMPLETE and trial.value is not None
    ]
    complete.sort(key=lambda trial: trial.value, reverse=True)
    for rank, trial in enumerate(complete[:10], 1):
        lines.append(
            f"| {rank} | {trial.number} | {trial.value:.3f} | "
            f"{trial.user_attrs.get('pooled_sharpe', 0):.3f} | "
            f"`{trial.user_attrs.get('fold_sharpes', [])}` | "
            f"`{trial.user_attrs.get('fold_trades', [])}` | "
            f"${trial.user_attrs.get('net_pnl_usd', 0):,.2f} |"
        )

    lines.extend([
        "",
        "## Interpretation",
        "",
        "The walk-forward windows reduce dependence on one lucky train/test cutoff, while "
        "the final holdout remains the clean generalization check. Optuna still compares "
        "many alternatives, and the sample can remain small, so a favorable result is a "
        "candidate for demo forward-testing—not permission to promote it automatically.",
        "",
        f"Total runtime: {elapsed:.1f} seconds.",
        "",
        "Reproduce from `backend/`:",
        "",
        "```powershell",
        f"python backtests/trendline_walk_forward.py --trials {args.trials} "
        f"--folds {args.folds} --lookback-days {args.lookback_days} --seed {args.seed}",
        "```",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--lookback-days", type=int, default=240)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--initial-train-fraction", type=float, default=0.50)
    parser.add_argument("--min-fold-trades", type=int, default=3)
    parser.add_argument("--stability-penalty", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("TRENDLINE_WALK_FORWARD_REPORT.md"),
    )
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    if args.folds < 2:
        parser.error("--folds must be at least 2")
    if args.lookback_days < 60:
        parser.error("--lookback-days must be at least 60")
    if not 0.1 <= args.holdout_fraction <= 0.4:
        parser.error("--holdout-fraction must be between 0.1 and 0.4")
    if not 0.25 <= args.initial_train_fraction <= 0.75:
        parser.error("--initial-train-fraction must be between 0.25 and 0.75")
    if args.min_fold_trades < 1:
        parser.error("--min-fold-trades must be positive")
    if args.stability_penalty < 0:
        parser.error("--stability-penalty cannot be negative")
    return args


def main() -> int:
    args = parse_args()
    logging.disable(logging.CRITICAL)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    started = time.perf_counter()

    print("Loading Trendline portfolio data ...", flush=True)
    portfolio, dates = load_portfolio(args.data_dir, args.lookback_days)
    folds, development, holdout_dates = make_folds(
        dates,
        args.holdout_fraction,
        args.folds,
        args.initial_train_fraction,
    )
    print(
        f"  symbols={', '.join(item.symbol for item in portfolio)}; "
        f"development={development[0]}..{development[-1]}; "
        f"holdout={holdout_dates[0]}..{holdout_dates[-1]}",
        flush=True,
    )

    baseline_folds = [
        evaluate_window(portfolio, baseline_params(), fold.validation_dates)
        for fold in folds
    ]
    study, best_params, optimized_folds = optimize(
        portfolio,
        folds,
        args.trials,
        args.seed,
        args.min_fold_trades,
        args.stability_penalty,
    )

    # This is deliberately after optimization: the search never sees holdout P/L.
    baseline_holdout = evaluate_window(portfolio, baseline_params(), holdout_dates)
    optimized_holdout = (
        baseline_holdout
        if study.best_trial.number == 0
        else evaluate_window(portfolio, best_params, holdout_dates)
    )

    elapsed = time.perf_counter() - started
    write_report(
        args.report.resolve(),
        args,
        portfolio,
        folds,
        development,
        holdout_dates,
        study,
        best_params,
        baseline_folds,
        optimized_folds,
        baseline_holdout,
        optimized_holdout,
        elapsed,
    )
    print(
        f"  holdout Sharpe: current={baseline_holdout.sharpe:.4f}, "
        f"optimized={optimized_holdout.sharpe:.4f}",
        flush=True,
    )
    print(f"Report written to {args.report.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
