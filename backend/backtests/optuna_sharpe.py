"""Chronological Optuna benchmark for the three live strategy portfolios.

The optimizer sees only the training partition.  The held-out test partition is
evaluated once, after Optuna has selected the best training configuration.

Run from ``backend``::

    python backtests/optuna_sharpe.py --trials 50
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from multi_symbol_targets import MB_TARGETS, SB_TARGETS, TL_TARGETS
from mutanabby.backtest import BacktestCosts as MutanabbyCosts
from mutanabby.backtest import run_backtest as run_mutanabby
from mutanabby.config import MutanabbyConfig
from mutanabby.data import prepare as prepare_mutanabby
from silver_bullet.backtest import run_backtest as run_silver_bullet
from silver_bullet.config import SilverBulletConfig
from silver_bullet.data import prepare as prepare_silver_bullet
from silver_bullet.metrics import compute_metrics
from trendline.backtest import BacktestCosts as TrendlineCosts
from trendline.backtest import run_backtest as run_trendline
from trendline.config import TrendlineConfig
from trendline.data import prepare_from_m5 as prepare_trendline


STRATEGIES = ("silver_bullet", "trendline", "mutanabby")
LABELS = {
    "silver_bullet": "Silver Bullet",
    "trendline": "Trendline",
    "mutanabby": "Mutanabby",
}
SYMBOL_TO_FILE = {
    "XAUUSDm": "xauusdm_m5_max.csv",
    "USTECm": "ustecm_m5_max.csv",
    "DE30m": "de30m_m5_max.csv",
    "USDJPYm": "usdjpym_m5_max.csv",
    "US30m": "us30_m5_max.csv",
    "JP225m": "jp225m_m5_max.csv",
    "ETHUSDm": "ethusdm_m5_max.csv",
}
TARGETS = {
    "silver_bullet": SB_TARGETS,
    "trendline": TL_TARGETS,
    "mutanabby": MB_TARGETS,
}
US30_MEDIAN_M5_RANGE = 24.9
TEST_WARMUP_BARS = 300


@dataclass
class DataBundle:
    symbol: str
    scale: float
    train_with_warmup: pd.DataFrame
    train_start: pd.Timestamp
    test_with_warmup: pd.DataFrame
    test_start: pd.Timestamp
    train_dates: list[date]
    test_dates: list[date]


@dataclass
class ExperimentResult:
    sharpe: float
    metrics: dict[str, Any]
    per_symbol: dict[str, dict[str, Any]]


def _m5_scale(path: Path) -> float:
    frame = pd.read_csv(path, usecols=["high", "low"])
    return float((frame["high"] - frame["low"]).median()) / US30_MEDIAN_M5_RANGE


def _prepare(strategy: str, path: Path, symbol: str) -> pd.DataFrame:
    if strategy == "silver_bullet":
        cfg = replace(SilverBulletConfig(), symbol=symbol, **SB_TARGETS[symbol])
        return prepare_silver_bullet(path, cfg)
    if strategy == "trendline":
        return prepare_trendline(path)
    return prepare_mutanabby(path, "1h")


def load_bundles(
    strategy: str,
    data_dir: Path,
    train_fraction: float,
    lookback_days: int | None,
) -> tuple[list[DataBundle], date]:
    prepared: list[tuple[str, float, pd.DataFrame]] = []
    all_dates: set[date] = set()
    first_dates: list[date] = []
    last_dates: list[date] = []

    for symbol in TARGETS[strategy]:
        path = data_dir / SYMBOL_TO_FILE[symbol]
        if not path.exists():
            raise FileNotFoundError(f"Missing data for {symbol}: {path}")
        scale = _m5_scale(path)
        frame = _prepare(strategy, path, symbol)
        prepared.append((symbol, scale, frame))
        frame_date_values = frame["timestamp_ny"].dt.date.tolist()
        all_dates.update(frame_date_values)
        first_dates.append(frame_date_values[0])
        last_dates.append(frame_date_values[-1])

    common_start = max(first_dates)
    common_end = min(last_dates)
    ordered_dates = sorted(day for day in all_dates if common_start <= day <= common_end)
    if lookback_days is not None:
        evaluation_start = common_end - pd.Timedelta(days=lookback_days - 1)
        ordered_dates = [day for day in ordered_dates if day >= evaluation_start]
    split_index = min(max(int(len(ordered_dates) * train_fraction), 1), len(ordered_dates) - 1)
    cutoff = ordered_dates[split_index]
    bundles: list[DataBundle] = []

    for symbol, scale, frame in prepared:
        frame_dates = frame["timestamp_ny"].dt.date
        train_mask = frame_dates.isin(ordered_dates[:split_index])
        test_mask = frame_dates.isin(ordered_dates[split_index:])
        if not train_mask.any() or not test_mask.any():
            raise ValueError(f"{symbol} has no data on one side of cutoff {cutoff}")

        first_train_position = int(np.flatnonzero(train_mask.to_numpy())[0])
        train_warmup_start = max(0, first_train_position - TEST_WARMUP_BARS)
        first_test_position = int(np.flatnonzero(test_mask.to_numpy())[0])
        warmup_start = max(0, first_test_position - TEST_WARMUP_BARS)
        train_start = frame.loc[train_mask, "timestamp_ny"].iloc[0]
        test_start = frame.loc[test_mask, "timestamp_ny"].iloc[0]
        bundles.append(
            DataBundle(
                symbol=symbol,
                scale=scale,
                train_with_warmup=frame.iloc[train_warmup_start:first_test_position].reset_index(drop=True),
                train_start=train_start,
                test_with_warmup=frame.iloc[warmup_start:].reset_index(drop=True),
                test_start=test_start,
                train_dates=sorted(set(frame.loc[train_mask, "timestamp_ny"].dt.date)),
                test_dates=sorted(set(frame.loc[test_mask, "timestamp_ny"].dt.date)),
            )
        )
    return bundles, cutoff


def daily_pnl_sharpe(trades: list[Any], trading_dates: list[date]) -> float:
    """Annualized Sharpe of daily fixed-risk P/L, with no-trade days as zero.

    The observed date frequency determines the annualization factor, so a
    weekday-only portfolio annualizes near 252 and a portfolio containing a
    weekend-traded crypto instrument annualizes near 365.
    """
    if len(trading_dates) < 2:
        return 0.0

    pnl_by_date = {day: 0.0 for day in trading_dates}
    for trade in trades:
        pnl = trade.pnl_dollars
        if pnl is None:
            continue
        timestamp = trade.exit_time if trade.exit_time is not None else trade.entry_time
        trade_date = timestamp.date() if timestamp is not None else date.fromisoformat(trade.date)
        if trade_date in pnl_by_date:
            pnl_by_date[trade_date] += float(pnl)

    daily = np.asarray([pnl_by_date[day] for day in trading_dates], dtype=float)
    std = float(np.std(daily, ddof=1))
    if not math.isfinite(std) or std <= 1e-12:
        return 0.0

    span_days = max((trading_dates[-1] - trading_dates[0]).days + 1, 1)
    periods_per_year = 365.25 * len(trading_dates) / span_days
    return float(np.mean(daily) / std * math.sqrt(periods_per_year))


def _sort_trades(trades: list[Any]) -> list[Any]:
    ceiling = pd.Timestamp.max.tz_localize("UTC")
    return sorted(trades, key=lambda trade: trade.exit_time or trade.entry_time or ceiling)


def _costs(cost_type: type, scale: float) -> Any:
    return cost_type(
        spread_points=2.0 * scale,
        slippage_points=1.0 * scale,
        commission_per_trade=5.0,
        risk_per_trade=100.0,
        point_value=1.0,
    )


def _silver_config(bundle: DataBundle, params: dict[str, Any]) -> SilverBulletConfig:
    overrides = SB_TARGETS[bundle.symbol]
    cfg = replace(
        SilverBulletConfig(),
        symbol=bundle.symbol,
        spread_points=2.0 * bundle.scale,
        slippage_points=1.0 * bundle.scale,
        commission_per_trade=5.0,
        risk_per_trade=100.0,
        point_value=1.0,
        **overrides,
    )
    if not params:
        return cfg
    updates = dict(params)
    updates["fvg_min_points"] = overrides["fvg_min_points"] * updates.pop("fvg_scale")
    updates["stop_buffer_points"] = overrides["stop_buffer_points"] * updates.pop("stop_buffer_scale")
    updates["min_risk_points"] = overrides["min_risk_points"] * updates.pop("min_risk_scale")
    return replace(cfg, **updates)


def _trendline_config(bundle: DataBundle, params: dict[str, Any]) -> TrendlineConfig:
    overrides = TL_TARGETS[bundle.symbol]
    cfg = replace(TrendlineConfig(), symbol=bundle.symbol, **overrides)
    if not params:
        return cfg
    updates = dict(params)
    updates["touch_tolerance_points"] = overrides["touch_tolerance_points"] * updates.pop("touch_scale")
    updates["obstruction_tolerance_points"] = overrides["obstruction_tolerance_points"] * updates.pop("obstruction_scale")
    updates["stop_buffer_points"] = overrides["stop_buffer_points"] * updates.pop("stop_buffer_scale")
    updates["min_risk_points"] = overrides["min_risk_points"] * updates.pop("min_risk_scale")
    if updates.get("split_targets"):
        updates["tp2_rr"] = updates["tp1_rr"] + updates.pop("tp2_gap")
    return replace(cfg, **updates)


def _mutanabby_config(bundle: DataBundle, params: dict[str, Any]) -> MutanabbyConfig:
    cfg = replace(MutanabbyConfig(), symbol=bundle.symbol, **MB_TARGETS[bundle.symbol])
    if not params:
        return cfg
    updates = dict(params)
    if updates.get("split_targets"):
        updates["tp2_rr"] = updates["tp1_rr"] + updates.pop("tp2_gap")
    return replace(cfg, **updates)


def run_portfolio(
    strategy: str,
    bundles: list[DataBundle],
    params: dict[str, Any],
    phase: str,
) -> ExperimentResult:
    all_trades: list[Any] = []
    all_dates: set[date] = set()
    symbol_trades: dict[str, list[Any]] = {}
    symbol_dates: dict[str, list[date]] = {}

    for bundle in bundles:
        frame = bundle.train_with_warmup if phase == "train" else bundle.test_with_warmup
        dates = bundle.train_dates if phase == "train" else bundle.test_dates
        if strategy == "silver_bullet":
            cfg = _silver_config(bundle, params)
            trades = run_silver_bullet(frame, cfg)
        elif strategy == "trendline":
            cfg = _trendline_config(bundle, params)
            trades = run_trendline(frame, cfg, _costs(TrendlineCosts, bundle.scale))
        else:
            cfg = _mutanabby_config(bundle, params)
            trades = run_mutanabby(frame, cfg, _costs(MutanabbyCosts, bundle.scale))

        phase_start = bundle.train_start if phase == "train" else bundle.test_start
        trades = [trade for trade in trades if trade.entry_time >= phase_start]
        trades = _sort_trades(trades)
        symbol_trades[bundle.symbol] = trades
        symbol_dates[bundle.symbol] = dates
        all_trades.extend(trades)
        all_dates.update(dates)

    all_trades = _sort_trades(all_trades)
    per_symbol: dict[str, dict[str, Any]] = {}
    for symbol, trades in symbol_trades.items():
        metrics = compute_metrics(trades)
        metrics["sharpe"] = round(daily_pnl_sharpe(trades, symbol_dates[symbol]), 4)
        per_symbol[symbol] = metrics

    return ExperimentResult(
        sharpe=daily_pnl_sharpe(all_trades, sorted(all_dates)),
        metrics=compute_metrics(all_trades),
        per_symbol=per_symbol,
    )


def suggest_params(strategy: str, trial: optuna.Trial) -> dict[str, Any]:
    if strategy == "silver_bullet":
        params: dict[str, Any] = {
            "swing_lookback": trial.suggest_int("swing_lookback", 2, 5),
            "sweep_lookback": trial.suggest_int("sweep_lookback", 6, 24, step=2),
            "fvg_scale": trial.suggest_float("fvg_scale", 0.6, 1.8, log=True),
            "stop_buffer_scale": trial.suggest_float("stop_buffer_scale", 0.5, 2.0, log=True),
            "min_risk_scale": trial.suggest_float("min_risk_scale", 0.5, 1.75, log=True),
            "entry_in_fvg": trial.suggest_categorical("entry_in_fvg", ["near_edge", "mid", "far_edge"]),
            "target_mode": trial.suggest_categorical("target_mode", ["opposite_liquidity", "rr"]),
            "breakeven_r": trial.suggest_categorical("breakeven_r", [0.0, 0.25, 0.5, 0.75, 1.0]),
            "early_exit_r": trial.suggest_categorical("early_exit_r", [0.0, 0.25, 0.4, 0.6]),
        }
        if params["target_mode"] == "rr":
            params["rr"] = trial.suggest_float("rr", 1.0, 4.0, step=0.25)
        params["trail_r"] = (
            trial.suggest_categorical("trail_r", [0.1, 0.25, 0.5])
            if params["breakeven_r"] > 0 else 0.0
        )
        return params

    if strategy == "trendline":
        params = {
            # Keep line construction at the current values. Broadening these
            # can create a combinatorial number of active candidate lines and
            # is too expensive for a repeatable portfolio study.
            "swing_lookback": 3,
            "steepness_max_ratio": 1.0,
            "touch_scale": trial.suggest_float("touch_scale", 0.5, 2.0, log=True),
            "obstruction_scale": 1.0,
            "stop_buffer_scale": trial.suggest_float("stop_buffer_scale", 0.5, 2.0, log=True),
            "min_risk_scale": trial.suggest_float("min_risk_scale", 0.5, 1.75, log=True),
            "candle_body_ratio_max": trial.suggest_float("candle_body_ratio_max", 0.15, 0.5),
            "candle_wick_ratio_min": trial.suggest_float("candle_wick_ratio_min", 1.0, 4.0),
            "split_targets": trial.suggest_categorical("split_targets", [True, False]),
            "breakeven_r": trial.suggest_categorical("breakeven_r", [0.0, 0.5, 1.0, 1.5]),
        }
        if params["split_targets"]:
            params["tp1_rr"] = trial.suggest_float("tp1_rr", 1.5, 4.0, step=0.5)
            params["tp2_gap"] = trial.suggest_float("tp2_gap", 0.5, 2.5, step=0.5)
            params["tp1_fraction"] = trial.suggest_categorical("tp1_fraction", [0.25, 0.5, 0.75])
        else:
            params["target_mode"] = trial.suggest_categorical("target_mode", ["opposite_swing", "rr"])
            params["rr"] = trial.suggest_float("rr", 1.5, 5.0, step=0.5)
            params["min_rr_for_swing_target"] = params["rr"]
        params["trail_r"] = (
            trial.suggest_categorical("trail_r", [0.25, 0.5, 0.75, 1.0])
            if params["breakeven_r"] > 0 else 0.0
        )
        return params

    params = {
        "sensitivity": trial.suggest_float("sensitivity", 4.5, 7.5, step=0.25),
        "supertrend_atr_length": trial.suggest_int("supertrend_atr_length", 7, 18),
        "trend_sma_length": trial.suggest_int("trend_sma_length", 8, 50),
        "risk_atr_length": trial.suggest_int("risk_atr_length", 7, 28),
        "atr_risk_multiplier": trial.suggest_float("atr_risk_multiplier", 0.5, 2.0, step=0.1),
        "split_targets": trial.suggest_categorical("split_targets", [True, False]),
        "breakeven_r": trial.suggest_categorical("breakeven_r", [0.0, 0.5, 1.0, 1.5]),
        "exit_on_opposite_signal": trial.suggest_categorical("exit_on_opposite_signal", [False, True]),
    }
    if params["split_targets"]:
        params["tp1_rr"] = trial.suggest_float("tp1_rr", 1.0, 3.5, step=0.5)
        params["tp2_gap"] = trial.suggest_float("tp2_gap", 0.5, 2.5, step=0.5)
        params["tp1_fraction"] = trial.suggest_categorical("tp1_fraction", [0.25, 0.5, 0.75])
    else:
        params["rr"] = trial.suggest_float("rr", 1.0, 4.0, step=0.25)
    params["trail_r"] = (
        trial.suggest_categorical("trail_r", [0.25, 0.5, 0.75, 1.0])
        if params["breakeven_r"] > 0 else 0.0
    )
    return params


def baseline_trial_params(strategy: str) -> dict[str, Any]:
    if strategy == "silver_bullet":
        return {
            "swing_lookback": 3,
            "sweep_lookback": 10,
            "fvg_scale": 1.0,
            "stop_buffer_scale": 1.0,
            "min_risk_scale": 1.0,
            "entry_in_fvg": "mid",
            "target_mode": "opposite_liquidity",
            "breakeven_r": 0.25,
            "early_exit_r": 0.4,
            "trail_r": 0.1,
        }
    if strategy == "trendline":
        return {
            "touch_scale": 1.0,
            "stop_buffer_scale": 1.0,
            "min_risk_scale": 1.0,
            "candle_body_ratio_max": 0.3,
            "candle_wick_ratio_min": 2.0,
            "split_targets": True,
            "breakeven_r": 1.0,
            "tp1_rr": 3.0,
            "tp2_gap": 1.0,
            "tp1_fraction": 0.5,
            "trail_r": 0.5,
        }
    return {
        "sensitivity": 6.0,
        "supertrend_atr_length": 11,
        "trend_sma_length": 13,
        "risk_atr_length": 14,
        "atr_risk_multiplier": 1.0,
        "split_targets": True,
        "breakeven_r": 0.0,
        "exit_on_opposite_signal": False,
        "tp1_rr": 3.0,
        "tp2_gap": 1.0,
        "tp1_fraction": 0.5,
    }


def optimize_strategy(
    strategy: str,
    bundles: list[DataBundle],
    trials: int,
    seed: int,
    min_trades: int,
    current_train: ExperimentResult,
) -> tuple[optuna.Study, dict[str, Any], ExperimentResult]:
    startup_trials = min(5, max(1, trials // 2))
    sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=startup_trials)
    study = optuna.create_study(direction="maximize", sampler=sampler, study_name=f"{strategy}_sharpe")
    study.enqueue_trial(baseline_trial_params(strategy))
    results_by_trial: dict[int, ExperimentResult] = {}

    def objective(trial: optuna.Trial) -> float:
        params = suggest_params(strategy, trial)
        result = current_train if trial.number == 0 else run_portfolio(strategy, bundles, params, "train")
        results_by_trial[trial.number] = result
        trial.set_user_attr("num_trades", result.metrics["num_trades"])
        trial.set_user_attr("net_pnl_usd", result.metrics["net_pnl_usd"])
        trial.set_user_attr("profit_factor", result.metrics["profit_factor"])
        if result.metrics["num_trades"] < min_trades:
            return -1_000.0 + result.metrics["num_trades"] / 1_000.0
        return result.sharpe

    def progress(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        completed = trial.number + 1
        if completed == 1 or completed % 10 == 0 or completed == trials:
            print(
                f"  {LABELS[strategy]}: {completed}/{trials} trials, "
                f"best train Sharpe={study.best_value:.4f}",
                flush=True,
            )

    study.optimize(objective, n_trials=trials, callbacks=[progress], gc_after_trial=True)
    best_params = suggest_params(strategy, optuna.trial.FixedTrial(study.best_params))
    best_train = results_by_trial[study.best_trial.number]
    return study, best_params, best_train


def _fmt(value: Any, digits: int = 2) -> str:
    if isinstance(value, str):
        return value
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{digits}f}"


def _result_row(strategy: str, version: str, phase: str, result: ExperimentResult) -> str:
    metrics = result.metrics
    return (
        f"| {LABELS[strategy]} | {version} | {phase} | {result.sharpe:.3f} | "
        f"{metrics['num_trades']} | ${metrics['net_pnl_usd']:,.2f} | "
        f"{_fmt(metrics['profit_factor'])} | ${metrics['max_drawdown_usd']:,.2f} | "
        f"{metrics['win_rate_pct']:.1f}% |"
    )


def _generalization_note(
    current_train: ExperimentResult,
    current_test: ExperimentResult,
    trained: ExperimentResult,
    test: ExperimentResult,
) -> str:
    if (
        trained.sharpe > current_train.sharpe
        and test.sharpe > current_test.sharpe
        and test.sharpe > 0
    ):
        return "Improved on both train and holdout; this is positive single-holdout evidence."
    if trained.sharpe > current_train.sharpe and test.sharpe <= current_test.sharpe:
        return "Train improved but holdout did not; treat this configuration as overfit."
    if test.sharpe > current_test.sharpe:
        return "Holdout improved despite limited train improvement; promising, but verify with walk-forward folds."
    return "No convincing holdout improvement over the current configuration."


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def write_report(
    path: Path,
    args: argparse.Namespace,
    records: dict[str, dict[str, Any]],
    elapsed: float,
) -> None:
    lines = [
        "# Optuna Sharpe Optimization Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Git commit: `{_git_commit()}`",
        "",
        "## Executive summary",
        "",
    ]
    for strategy, record in records.items():
        current_test = record["current_test"]
        current_train = record["current_train"]
        optimized_train = record["optimized_train"]
        optimized_test = record["optimized_test"]
        lines.append(
            f"- **{LABELS[strategy]}:** test Sharpe {_fmt(current_test.sharpe, 3)} → "
            f"{_fmt(optimized_test.sharpe, 3)}. "
            f"{_generalization_note(current_train, current_test, optimized_train, optimized_test)}"
        )

    lines.extend(["", "## Recommendation", ""])
    for strategy, record in records.items():
        current_test = record["current_test"]
        optimized_test = record["optimized_test"]
        if optimized_test.sharpe <= current_test.sharpe:
            recommendation = "Retain the current parameters; the Optuna winner failed the holdout."
        elif optimized_test.metrics["num_trades"] < 30:
            recommendation = (
                "Do not promote automatically. Forward-test the candidate and run multiple walk-forward folds; "
                f"the holdout contains only {optimized_test.metrics['num_trades']} trades."
            )
        else:
            recommendation = "Promising holdout result; validate with multiple walk-forward folds before live promotion."
        weaker_symbols = [
            symbol
            for symbol, metrics in optimized_test.per_symbol.items()
            if metrics["net_pnl_usd"] < current_test.per_symbol[symbol]["net_pnl_usd"]
        ]
        if weaker_symbols and optimized_test.sharpe > current_test.sharpe:
            recommendation += f" Holdout net P/L worsened for {', '.join(weaker_symbols)}."
        lines.append(f"- **{LABELS[strategy]}:** {recommendation}")

    lines.extend([
        "",
        "## Method",
        "",
        f"- Objective: maximize annualized daily-P/L Sharpe on the training set only.",
        f"- Split: first {args.train_fraction:.0%} of available dates for training, final "
        f"{1.0 - args.train_fraction:.0%} for the untouched holdout.",
        f"- Optimizer: Optuna TPE, seed `{args.seed}`. Trial budgets: Silver Bullet `{args.trials}`, Trendline `{args.trendline_trials}`, Mutanabby `{args.trials}`.",
        f"- History window: the final `{args.lookback_days}` calendar days available to each portfolio.",
        f"- Guardrail: trials with fewer than `{args.min_trades}` aggregate training trades receive an invalid score.",
        "- Trendline runtime guard: swing lookback, steepness, and obstruction geometry stay at current values; the study tunes touch sensitivity, risk filters, candle confirmation, targets, and trade management.",
        f"- Test initialization: `{TEST_WARMUP_BARS}` pre-cutoff bars initialize indicators; only post-cutoff entries are scored.",
        "- Sharpe: mean daily fixed-risk P/L divided by sample daily-P/L volatility, annualized from the observed trading-date frequency. No-trade dates present in the source data count as zero; risk-free rate is zero.",
        "- Costs: the repository's standard $5 round-trip commission, with spread and slippage scaled from each instrument's median M5 range. Risk is fixed at $100 per trade.",
        "- Current benchmark: the configurations actually constructed by `bot.py`, including per-symbol overrides from `multi_symbol_targets.py`.",
        "",
        "## Data partitions",
        "",
        "| Strategy | Symbols | Cutoff (test starts) | Train dates | Test dates |",
        "| --- | --- | --- | ---: | ---: |",
    ])
    for strategy, record in records.items():
        bundles: list[DataBundle] = record["bundles"]
        train_dates = sorted({day for bundle in bundles for day in bundle.train_dates})
        test_dates = sorted({day for bundle in bundles for day in bundle.test_dates})
        lines.append(
            f"| {LABELS[strategy]} | {', '.join(bundle.symbol for bundle in bundles)} | "
            f"{record['cutoff']} | {len(train_dates)} | {len(test_dates)} |"
        )

    lines.extend([
        "",
        "## Aggregate results",
        "",
        "| Strategy | Configuration | Partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for strategy, record in records.items():
        lines.append(_result_row(strategy, "Current", "Train", record["current_train"]))
        lines.append(_result_row(strategy, "Current", "Test", record["current_test"]))
        lines.append(_result_row(strategy, "Optuna", "Train", record["optimized_train"]))
        lines.append(_result_row(strategy, "Optuna", "Test", record["optimized_test"]))

    lines.extend(["", "## Holdout results by symbol", ""])
    for strategy, record in records.items():
        lines.extend([
            f"### {LABELS[strategy]}",
            "",
            "| Symbol | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        current = record["current_test"].per_symbol
        optimized = record["optimized_test"].per_symbol
        for symbol in current:
            lines.append(
                f"| {symbol} | {_fmt(current[symbol]['sharpe'], 3)} | "
                f"{_fmt(optimized[symbol]['sharpe'], 3)} | {current[symbol]['num_trades']} | "
                f"{optimized[symbol]['num_trades']} | ${current[symbol]['net_pnl_usd']:,.2f} | "
                f"${optimized[symbol]['net_pnl_usd']:,.2f} |"
            )
        lines.append("")

    lines.extend(["## Selected parameters", ""])
    for strategy, record in records.items():
        lines.extend([
            f"### {LABELS[strategy]}",
            "",
            "```json",
            json.dumps(record["best_params"], indent=2, sort_keys=True),
            "```",
            "",
            "Top five training trials:",
            "",
            "| Rank | Trial | Train Sharpe | Trades | Net P/L | Parameters |",
            "| ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        complete = [
            trial for trial in record["study"].trials
            if trial.state == optuna.trial.TrialState.COMPLETE and trial.value is not None
        ]
        complete.sort(key=lambda trial: trial.value, reverse=True)
        for rank, trial in enumerate(complete[:5], 1):
            params = json.dumps(trial.params, sort_keys=True).replace("|", "\\|")
            lines.append(
                f"| {rank} | {trial.number} | {trial.value:.3f} | "
                f"{trial.user_attrs.get('num_trades', 'n/a')} | "
                f"${trial.user_attrs.get('net_pnl_usd', 0):,.2f} | `{params}` |"
            )
        lines.append("")

    lines.extend([
        "## Interpretation and limitations",
        "",
        "This is a clean chronological holdout, but it is still one historical split. A higher test Sharpe is evidence of generalization, not proof. The search evaluates many parameter combinations, transaction costs are approximations, fixed-dollar risk is not a full account-equity simulation, and live fills can differ materially. Before changing live settings, repeat the result over several walk-forward folds and forward-test it on demo.",
        "",
        f"Total runtime: {elapsed:.1f} seconds.",
        "",
        "Reproduce from `backend/`:",
        "",
        "```powershell",
        f"python backtests/optuna_sharpe.py --trials {args.trials} --trendline-trials {args.trendline_trials} --train-fraction {args.train_fraction} --lookback-days {args.lookback_days} --seed {args.seed} --min-trades {args.min_trades}",
        "```",
        "",
    ])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=20, help="Optuna trials for Silver Bullet and Mutanabby")
    parser.add_argument("--trendline-trials", type=int, default=8, help="Optuna trials for the slower Trendline engine")
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--lookback-days", type=int, default=240)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--min-trades", type=int, default=15)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--report", type=Path, default=Path(__file__).with_name("OPTUNA_SHARPE_REPORT.md"))
    parser.add_argument(
        "--strategies",
        nargs="+",
        choices=(*STRATEGIES, "all"),
        default=["all"],
    )
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    if args.trendline_trials < 1:
        parser.error("--trendline-trials must be positive")
    if not 0.5 <= args.train_fraction <= 0.9:
        parser.error("--train-fraction must be between 0.5 and 0.9")
    if args.min_trades < 1:
        parser.error("--min-trades must be positive")
    if args.lookback_days < 60:
        parser.error("--lookback-days must be at least 60")
    return args


def main() -> int:
    args = parse_args()
    logging.disable(logging.CRITICAL)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    selected = list(STRATEGIES) if "all" in args.strategies else list(dict.fromkeys(args.strategies))
    records: dict[str, dict[str, Any]] = {}
    started = time.perf_counter()

    for offset, strategy in enumerate(selected):
        print(f"\n{LABELS[strategy]}: loading portfolio data ...", flush=True)
        bundles, cutoff = load_bundles(
            strategy, args.data_dir, args.train_fraction, args.lookback_days
        )
        print(
            f"  symbols={', '.join(bundle.symbol for bundle in bundles)}; test starts {cutoff}",
            flush=True,
        )
        current_train = run_portfolio(strategy, bundles, {}, "train")
        current_test = run_portfolio(strategy, bundles, {}, "test")
        print(
            f"  current Sharpe: train={current_train.sharpe:.4f}, test={current_test.sharpe:.4f}",
            flush=True,
        )
        study, best_params, optimized_train = optimize_strategy(
            strategy,
            bundles,
            args.trendline_trials if strategy == "trendline" else args.trials,
            args.seed + offset,
            args.min_trades,
            current_train,
        )
        optimized_test = (
            current_test
            if study.best_trial.number == 0
            else run_portfolio(strategy, bundles, best_params, "test")
        )
        print(
            f"  Optuna Sharpe: train={optimized_train.sharpe:.4f}, test={optimized_test.sharpe:.4f}",
            flush=True,
        )
        records[strategy] = {
            "bundles": bundles,
            "cutoff": cutoff,
            "current_train": current_train,
            "current_test": current_test,
            "study": study,
            "best_params": best_params,
            "optimized_train": optimized_train,
            "optimized_test": optimized_test,
        }

    elapsed = time.perf_counter() - started
    write_report(args.report.resolve(), args, records, elapsed)
    print(f"\nReport written to {args.report.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
