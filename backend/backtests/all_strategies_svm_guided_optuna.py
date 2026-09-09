"""SVM-guided, constrained walk-forward optimization for all live strategies.

For each strategy independently:
1. Generate baseline trades on the development period.
2. Fit an SVM on the early trades and measure permutation importance later.
3. Map actionable features to at most three existing strategy parameters.
4. Let Optuna vary only those parameters over chronological forward folds.
5. Evaluate the selected candidate once on an untouched final holdout.

Run from ``backend``::

    python backtests/all_strategies_svm_guided_optuna.py --trials 30
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import optuna
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.inspection import permutation_importance
from sklearn.metrics import accuracy_score, balanced_accuracy_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import SVC

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.optuna_sharpe import (  # noqa: E402
    LABELS,
    SYMBOL_TO_FILE,
    TARGETS,
    TEST_WARMUP_BARS,
    _costs,
    _m5_scale,
    _mutanabby_config,
    _prepare,
    _silver_config,
    _sort_trades,
    _trendline_config,
    baseline_trial_params,
    daily_pnl_sharpe,
)
from backtests.trendline_walk_forward import baseline_params as trendline_baseline  # noqa: E402
from mutanabby.backtest import BacktestCosts as MutanabbyCosts  # noqa: E402
from mutanabby.backtest import run_backtest as run_mutanabby  # noqa: E402
from mutanabby.indicators import atr, sma, supertrend  # noqa: E402
from silver_bullet.backtest import run_backtest as run_silver_bullet  # noqa: E402
from silver_bullet.metrics import compute_metrics  # noqa: E402
from trendline.backtest import BacktestCosts as TrendlineCosts  # noqa: E402
from trendline.backtest import run_backtest as run_trendline  # noqa: E402


STRATEGIES = ("silver_bullet", "trendline", "mutanabby")
BASE_CATEGORICAL = ["symbol", "direction"]
BASE_NUMERIC = [
    "risk_to_range",
    "entry_gap_r",
    "planned_reward_r",
    "candle_range_vs_24h",
    "body_ratio",
    "upper_wick_ratio",
    "lower_wick_ratio",
    "close_location",
    "directional_candle_body",
    "return_1h",
    "return_3h",
    "return_6h",
    "return_24h",
    "directional_return_6h",
    "price_vs_sma20_range",
    "return_volatility_24h",
    "hour_sin",
    "hour_cos",
    "weekday",
]
EXTRA_FEATURES = {
    "silver_bullet": {
        "categorical": ["window"],
        "numeric": ["fvg_size_to_range", "sweep_gap_to_range", "bars_sweep_to_signal"],
    },
    "trendline": {
        "categorical": [],
        "numeric": [
            "line_anchor_span",
            "line_age",
            "directional_line_slope",
            "touch_gap_to_range",
        ],
    },
    "mutanabby": {
        "categorical": ["signal_strength"],
        "numeric": [
            "rsi_at_signal",
            "supertrend_gap_to_range",
            "trend_sma_gap_to_range",
            "atr_to_range",
        ],
    },
}
PARAMETER_FEATURES: dict[str, dict[str, tuple[str, ...]]] = {
    "silver_bullet": {
        "swing_lookback": ("sweep_gap_to_range",),
        "sweep_lookback": ("bars_sweep_to_signal",),
        "fvg_scale": ("fvg_size_to_range",),
        "entry_in_fvg": ("entry_gap_r",),
        "stop_buffer_scale": ("entry_gap_r", "risk_to_range"),
        "min_risk_scale": ("risk_to_range",),
    },
    "trendline": {
        "candle_body_ratio_max": (
            "body_ratio",
            "directional_candle_body",
            "close_location",
        ),
        "candle_wick_ratio_min": ("upper_wick_ratio", "lower_wick_ratio"),
        "swing_lookback": ("line_anchor_span", "line_age"),
        "steepness_max_ratio": ("directional_line_slope",),
        "stop_buffer_scale": ("entry_gap_r", "risk_to_range"),
        "min_risk_scale": ("risk_to_range",),
        "touch_scale": ("touch_gap_to_range",),
    },
    "mutanabby": {
        "sensitivity": ("supertrend_gap_to_range", "return_volatility_24h"),
        "supertrend_atr_length": ("supertrend_gap_to_range", "atr_to_range"),
        "trend_sma_length": ("trend_sma_gap_to_range", "price_vs_sma20_range"),
        "risk_atr_length": ("atr_to_range", "risk_to_range"),
        "atr_risk_multiplier": ("risk_to_range",),
    },
}


@dataclass
class PortfolioItem:
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
    per_symbol_trades: dict[str, list[Any]]
    dates: list[date]


@dataclass
class SVMResult:
    train: pd.DataFrame
    validation: pd.DataFrame
    metrics: dict[str, float]
    permutation: list[tuple[str, float, float]]


@dataclass
class StrategyRecord:
    portfolio: list[PortfolioItem]
    folds: list[Fold]
    development_dates: list[date]
    holdout_dates: list[date]
    svm: SVMResult
    parameter_ranking: list[tuple[str, float, tuple[str, ...]]]
    selected: list[str]
    study: optuna.Study
    best_params: dict[str, Any]
    baseline_folds: list[WindowResult]
    optimized_folds: list[WindowResult]
    baseline_holdout: WindowResult
    optimized_holdout: WindowResult


def feature_names(strategy: str) -> tuple[list[str], list[str], list[str]]:
    categorical = BASE_CATEGORICAL + EXTRA_FEATURES[strategy]["categorical"]
    numeric = BASE_NUMERIC + EXTRA_FEATURES[strategy]["numeric"]
    return categorical, numeric, categorical + numeric


def current_params(strategy: str) -> dict[str, Any]:
    if strategy == "trendline":
        return trendline_baseline()
    return baseline_trial_params(strategy)


def load_portfolio(
    strategy: str,
    data_dir: Path,
    lookback_days: int,
) -> tuple[list[PortfolioItem], list[date]]:
    portfolio: list[PortfolioItem] = []
    first_dates: list[date] = []
    last_dates: list[date] = []
    all_dates: set[date] = set()
    for symbol in TARGETS[strategy]:
        path = data_dir / SYMBOL_TO_FILE[symbol]
        if not path.exists():
            raise FileNotFoundError(f"Missing data for {symbol}: {path}")
        frame = _prepare(strategy, path, symbol)
        dates = frame["timestamp_ny"].dt.date
        portfolio.append(PortfolioItem(symbol, _m5_scale(path), frame))
        first_dates.append(dates.iloc[0])
        last_dates.append(dates.iloc[-1])
        all_dates.update(dates.tolist())

    common_start = max(first_dates)
    common_end = min(last_dates)
    requested_start = (
        pd.Timestamp(common_end) - pd.Timedelta(days=lookback_days - 1)
    ).date()
    start = max(common_start, requested_start)
    dates = sorted(day for day in all_dates if start <= day <= common_end)
    if len(dates) < 20:
        raise RuntimeError(f"Not enough {LABELS[strategy]} history")
    return portfolio, dates


def make_folds(
    dates: list[date],
    holdout_fraction: float,
    fold_count: int,
    initial_train_fraction: float,
) -> tuple[list[Fold], list[date], list[date]]:
    development_end = min(
        max(int(len(dates) * (1.0 - holdout_fraction)), 2), len(dates) - 1
    )
    development = dates[:development_end]
    holdout = dates[development_end:]
    max_initial = len(development) - fold_count
    if max_initial < 1:
        raise RuntimeError("Not enough development dates for the requested folds")
    initial_end = min(
        max(int(len(development) * initial_train_fraction), 1), max_initial
    )
    blocks = [
        list(block)
        for block in np.array_split(development[initial_end:], fold_count)
        if len(block)
    ]
    folds: list[Fold] = []
    consumed = initial_end
    for number, block in enumerate(blocks, 1):
        folds.append(Fold(number, development[:consumed], block))
        consumed += len(block)
    return folds, development, holdout


def _run(
    strategy: str,
    item: PortfolioItem,
    params: dict[str, Any],
    frame: pd.DataFrame,
) -> list[Any]:
    if strategy == "silver_bullet":
        return run_silver_bullet(frame, _silver_config(item, params))
    if strategy == "trendline":
        return run_trendline(
            frame,
            _trendline_config(item, params),
            _costs(TrendlineCosts, item.scale),
        )
    return run_mutanabby(
        frame,
        _mutanabby_config(item, params),
        _costs(MutanabbyCosts, item.scale),
    )


def run_symbol_window(
    strategy: str,
    item: PortfolioItem,
    params: dict[str, Any],
    dates: list[date],
) -> tuple[pd.DataFrame, list[Any], list[date]]:
    wanted = set(dates)
    frame_dates = item.frame["timestamp_ny"].dt.date
    positions = np.flatnonzero(frame_dates.isin(wanted).to_numpy())
    if not len(positions):
        return item.frame.iloc[:0].copy(), [], []
    warmup_start = max(0, int(positions[0]) - TEST_WARMUP_BARS)
    stop = int(positions[-1]) + 1
    frame = item.frame.iloc[warmup_start:stop].reset_index(drop=True)
    trades = _run(strategy, item, params, frame)
    trades = _sort_trades(
        [trade for trade in trades if trade.entry_time.date() in wanted]
    )
    symbol_dates = sorted(set(frame_dates.iloc[positions].tolist()))
    return frame, trades, symbol_dates


def evaluate_window(
    strategy: str,
    portfolio: list[PortfolioItem],
    params: dict[str, Any],
    dates: list[date],
) -> WindowResult:
    all_trades: list[Any] = []
    per_symbol: dict[str, dict[str, Any]] = {}
    per_symbol_trades: dict[str, list[Any]] = {}
    for item in portfolio:
        _, trades, symbol_dates = run_symbol_window(strategy, item, params, dates)
        metrics = compute_metrics(trades)
        metrics["sharpe"] = daily_pnl_sharpe(trades, symbol_dates)
        per_symbol[item.symbol] = metrics
        per_symbol_trades[item.symbol] = trades
        all_trades.extend(trades)
    all_trades = _sort_trades(all_trades)
    return WindowResult(
        daily_pnl_sharpe(all_trades, dates),
        compute_metrics(all_trades),
        per_symbol,
        per_symbol_trades,
        dates,
    )


def pooled_result(results: list[WindowResult]) -> WindowResult:
    dates = sorted({day for result in results for day in result.dates})
    symbols = list(results[0].per_symbol)
    per_symbol_trades = {
        symbol: _sort_trades(
            [trade for result in results for trade in result.per_symbol_trades[symbol]]
        )
        for symbol in symbols
    }
    per_symbol: dict[str, dict[str, Any]] = {}
    all_trades: list[Any] = []
    for symbol, trades in per_symbol_trades.items():
        metrics = compute_metrics(trades)
        metrics["sharpe"] = daily_pnl_sharpe(trades, dates)
        per_symbol[symbol] = metrics
        all_trades.extend(trades)
    all_trades = _sort_trades(all_trades)
    return WindowResult(
        daily_pnl_sharpe(all_trades, dates),
        compute_metrics(all_trades),
        per_symbol,
        per_symbol_trades,
        dates,
    )


def _base_feature_row(
    trade: Any,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    bar_idx: int,
    symbol: str,
) -> dict[str, Any] | None:
    if bar_idx < 24 or bar_idx >= len(closes):
        return None
    candle_range = max(float(highs[bar_idx] - lows[bar_idx]), 1e-9)
    ranges = highs - lows
    avg_range = max(float(np.mean(ranges[bar_idx - 23:bar_idx + 1])), 1e-9)
    body = abs(float(closes[bar_idx] - opens[bar_idx]))
    upper = float(highs[bar_idx] - max(opens[bar_idx], closes[bar_idx]))
    lower = float(min(opens[bar_idx], closes[bar_idx]) - lows[bar_idx])
    sign = 1.0 if trade.direction == "long" else -1.0
    risk = max(float(trade.risk_points), 1e-9)
    target1_r = abs(float(trade.target_price - trade.entry_price)) / risk
    if trade.target_price_2 is not None:
        target2_r = abs(float(trade.target_price_2 - trade.entry_price)) / risk
        planned_reward = trade.tp1_fraction * target1_r + (1.0 - trade.tp1_fraction) * target2_r
    else:
        planned_reward = target1_r
    returns = {
        horizon: float(closes[bar_idx] / closes[bar_idx - horizon] - 1.0)
        for horizon in (1, 3, 6, 24)
    }
    log_returns = np.diff(np.log(np.maximum(closes[bar_idx - 24:bar_idx + 1], 1e-9)))
    sma20 = float(np.mean(closes[bar_idx - 19:bar_idx + 1]))
    hour = trade.entry_time.hour + trade.entry_time.minute / 60.0
    exit_timestamp = trade.exit_time or trade.entry_time
    return {
        "symbol": symbol,
        "direction": trade.direction,
        "risk_to_range": risk / avg_range,
        "entry_gap_r": abs(float(trade.entry_price - closes[bar_idx])) / risk,
        "planned_reward_r": planned_reward,
        "candle_range_vs_24h": candle_range / avg_range,
        "body_ratio": body / candle_range,
        "upper_wick_ratio": upper / candle_range,
        "lower_wick_ratio": lower / candle_range,
        "close_location": float(closes[bar_idx] - lows[bar_idx]) / candle_range,
        "directional_candle_body": sign * float(closes[bar_idx] - opens[bar_idx]) / candle_range,
        "return_1h": returns[1],
        "return_3h": returns[3],
        "return_6h": returns[6],
        "return_24h": returns[24],
        "directional_return_6h": sign * returns[6],
        "price_vs_sma20_range": float(closes[bar_idx] - sma20) / avg_range,
        "return_volatility_24h": float(np.std(log_returns, ddof=1)),
        "hour_sin": math.sin(2.0 * math.pi * hour / 24.0),
        "hour_cos": math.cos(2.0 * math.pi * hour / 24.0),
        "weekday": float(trade.entry_time.weekday()),
        "entry_time": trade.entry_time,
        "exit_date": exit_timestamp.date(),
        "pnl_usd": float(trade.pnl_dollars or 0.0),
        "won": int((trade.pnl_dollars or 0.0) > 0.0),
        "_avg_range": avg_range,
        "_direction_sign": sign,
    }


def feature_rows(
    strategy: str,
    item: PortfolioItem,
    frame: pd.DataFrame,
    trades: list[Any],
) -> list[dict[str, Any]]:
    opens = frame["open"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    extra_arrays: dict[str, np.ndarray] = {}
    if strategy == "mutanabby":
        cfg = _mutanabby_config(item, current_params(strategy))
        st, _ = supertrend(highs, lows, closes, cfg.sensitivity, cfg.supertrend_atr_length)
        extra_arrays = {
            "supertrend": st,
            "trend_sma": sma(closes, cfg.trend_sma_length),
            "risk_atr": atr(highs, lows, closes, cfg.risk_atr_length),
        }

    rows: list[dict[str, Any]] = []
    for trade in trades:
        bar_idx = int(
            trade.fvg_bar
            if strategy == "silver_bullet"
            else trade.touch_bar
            if strategy == "trendline"
            else trade.signal_bar
        )
        row = _base_feature_row(trade, opens, highs, lows, closes, bar_idx, item.symbol)
        if row is None:
            continue
        avg_range = row.pop("_avg_range")
        sign = row.pop("_direction_sign")
        if strategy == "silver_bullet":
            zone_bottom, zone_top = trade.fvg_zone
            row.update(
                {
                    "window": f"window_{trade.window_id}",
                    "fvg_size_to_range": abs(float(zone_top - zone_bottom)) / avg_range,
                    "sweep_gap_to_range": abs(float(closes[bar_idx] - trade.sweep_level)) / avg_range,
                    "bars_sweep_to_signal": float(bar_idx - trade.sweep_bar),
                }
            )
        elif strategy == "trendline":
            anchor1 = int(trade.line_anchor1_bar)
            anchor2 = int(trade.line_anchor2_bar)
            if not (0 <= anchor1 < anchor2 <= bar_idx):
                continue
            line_prices = lows if trade.line_kind == "support" else highs
            slope = float(line_prices[anchor2] - line_prices[anchor1]) / (anchor2 - anchor1)
            line_value = float(line_prices[anchor1]) + slope * (bar_idx - anchor1)
            touch_price = lows[bar_idx] if trade.line_kind == "support" else highs[bar_idx]
            row.update(
                {
                    "line_anchor_span": float(anchor2 - anchor1),
                    "line_age": float(bar_idx - anchor2),
                    "directional_line_slope": sign * slope / avg_range,
                    "touch_gap_to_range": abs(float(touch_price - line_value)) / avg_range,
                }
            )
        else:
            row.update(
                {
                    "signal_strength": trade.strength,
                    "rsi_at_signal": float(trade.rsi_at_signal),
                    "supertrend_gap_to_range": sign
                    * float(closes[bar_idx] - extra_arrays["supertrend"][bar_idx])
                    / avg_range,
                    "trend_sma_gap_to_range": sign
                    * float(closes[bar_idx] - extra_arrays["trend_sma"][bar_idx])
                    / avg_range,
                    "atr_to_range": float(extra_arrays["risk_atr"][bar_idx]) / avg_range,
                }
            )
        rows.append(row)
    return rows


def baseline_dataset(
    strategy: str,
    portfolio: list[PortfolioItem],
    development_dates: list[date],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    params = current_params(strategy)
    for item in portfolio:
        frame, trades, _ = run_symbol_window(
            strategy, item, params, development_dates
        )
        rows.extend(feature_rows(strategy, item, frame, trades))
    _, _, features = feature_names(strategy)
    result = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    result = result.dropna(subset=features + ["won"]).sort_values("entry_time")
    result = result.reset_index(drop=True)
    if len(result) < 20:
        raise RuntimeError(f"Only {len(result)} usable baseline {LABELS[strategy]} trades")
    return result


def split_svm_rows(
    rows: pd.DataFrame, train_fraction: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    target = int(len(rows) * train_fraction)
    candidates = sorted(
        range(max(2, int(len(rows) * 0.5)), min(len(rows) - 1, int(len(rows) * 0.85)) + 1),
        key=lambda split: abs(split - target),
    )
    for split in candidates:
        train = rows.iloc[:split]
        validation = rows.iloc[split:]
        if train["won"].nunique() == 2 and validation["won"].nunique() == 2:
            return train.copy(), validation.copy()
    raise RuntimeError("Could not create two chronological SVM partitions with both classes")


def fit_svm(
    strategy: str,
    rows: pd.DataFrame,
    train_fraction: float,
    repeats: int,
    seed: int,
) -> SVMResult:
    categorical, numeric, features = feature_names(strategy)
    train, validation = split_svm_rows(rows, train_fraction)
    transformer = ColumnTransformer(
        [
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                categorical,
            ),
            ("numeric", StandardScaler(), numeric),
        ]
    )
    pipeline = Pipeline(
        [
            ("features", transformer),
            ("svm", SVC(kernel="linear", C=0.25, class_weight="balanced")),
        ]
    )
    pipeline.fit(train[features], train["won"])
    predictions = pipeline.predict(validation[features])
    decision = pipeline.decision_function(validation[features])
    metrics = {
        "accuracy": accuracy_score(validation["won"], predictions),
        "balanced_accuracy": balanced_accuracy_score(validation["won"], predictions),
        "roc_auc": roc_auc_score(validation["won"], decision),
        "majority_accuracy": max(
            float(validation["won"].mean()), 1.0 - float(validation["won"].mean())
        ),
    }
    importance = permutation_importance(
        pipeline,
        validation[features],
        validation["won"],
        scoring="balanced_accuracy",
        n_repeats=repeats,
        random_state=seed,
    )
    permutation = sorted(
        [
            (feature, float(mean), float(std))
            for feature, mean, std in zip(
                features, importance.importances_mean, importance.importances_std
            )
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    return SVMResult(train, validation, metrics, permutation)


def rank_parameters(
    strategy: str,
    permutation: list[tuple[str, float, float]],
    maximum: int,
) -> tuple[list[str], list[tuple[str, float, tuple[str, ...]]]]:
    feature_scores = {feature: max(0.0, mean) for feature, mean, _ in permutation}
    ranking = sorted(
        [
            (
                parameter,
                sum(feature_scores.get(feature, 0.0) for feature in features),
                features,
            )
            for parameter, features in PARAMETER_FEATURES[strategy].items()
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    selected = [parameter for parameter, score, _ in ranking if score > 0][:maximum]
    if not selected:
        raise RuntimeError(f"SVM found no actionable {LABELS[strategy]} parameters")
    return selected, ranking


def suggest_guided(
    strategy: str,
    trial: optuna.Trial,
    selected: list[str],
) -> dict[str, Any]:
    params = current_params(strategy)
    if strategy == "silver_bullet":
        if "swing_lookback" in selected:
            params["swing_lookback"] = trial.suggest_int("swing_lookback", 2, 5)
        if "sweep_lookback" in selected:
            params["sweep_lookback"] = trial.suggest_int("sweep_lookback", 6, 24, step=2)
        if "fvg_scale" in selected:
            params["fvg_scale"] = trial.suggest_float("fvg_scale", 0.6, 1.8, log=True)
        if "entry_in_fvg" in selected:
            params["entry_in_fvg"] = trial.suggest_categorical(
                "entry_in_fvg", ["near_edge", "mid", "far_edge"]
            )
        if "stop_buffer_scale" in selected:
            params["stop_buffer_scale"] = trial.suggest_float(
                "stop_buffer_scale", 0.5, 2.0, log=True
            )
        if "min_risk_scale" in selected:
            params["min_risk_scale"] = trial.suggest_float(
                "min_risk_scale", 0.5, 1.75, log=True
            )
    elif strategy == "trendline":
        if "candle_body_ratio_max" in selected:
            params["candle_body_ratio_max"] = trial.suggest_float(
                "candle_body_ratio_max", 0.20, 0.40
            )
        if "candle_wick_ratio_min" in selected:
            params["candle_wick_ratio_min"] = trial.suggest_float(
                "candle_wick_ratio_min", 1.5, 3.0
            )
        if "swing_lookback" in selected:
            params["swing_lookback"] = trial.suggest_int("swing_lookback", 2, 5)
        if "steepness_max_ratio" in selected:
            params["steepness_max_ratio"] = trial.suggest_float(
                "steepness_max_ratio", 0.5, 1.5, step=0.25
            )
        if "stop_buffer_scale" in selected:
            params["stop_buffer_scale"] = trial.suggest_float(
                "stop_buffer_scale", 0.7, 1.5, log=True
            )
        if "min_risk_scale" in selected:
            params["min_risk_scale"] = trial.suggest_float(
                "min_risk_scale", 0.7, 1.5, log=True
            )
        if "touch_scale" in selected:
            params["touch_scale"] = trial.suggest_float("touch_scale", 0.6, 1.5, log=True)
    else:
        if "sensitivity" in selected:
            params["sensitivity"] = trial.suggest_float("sensitivity", 4.5, 7.5, step=0.25)
        if "supertrend_atr_length" in selected:
            params["supertrend_atr_length"] = trial.suggest_int(
                "supertrend_atr_length", 7, 18
            )
        if "trend_sma_length" in selected:
            params["trend_sma_length"] = trial.suggest_int("trend_sma_length", 8, 50)
        if "risk_atr_length" in selected:
            params["risk_atr_length"] = trial.suggest_int("risk_atr_length", 7, 28)
        if "atr_risk_multiplier" in selected:
            params["atr_risk_multiplier"] = trial.suggest_float(
                "atr_risk_multiplier", 0.5, 2.0, step=0.1
            )
    return params


def optimize_guided(
    strategy: str,
    portfolio: list[PortfolioItem],
    folds: list[Fold],
    selected: list[str],
    trials: int,
    seed: int,
    min_fold_trades: int,
    stability_penalty: float,
) -> tuple[optuna.Study, dict[str, Any], list[WindowResult]]:
    sampler = optuna.samplers.TPESampler(
        seed=seed, n_startup_trials=min(10, max(1, trials // 3))
    )
    study = optuna.create_study(direction="maximize", sampler=sampler)
    baseline = current_params(strategy)
    study.enqueue_trial({parameter: baseline[parameter] for parameter in selected})
    results_by_trial: dict[int, list[WindowResult]] = {}

    def objective(trial: optuna.Trial) -> float:
        params = suggest_guided(strategy, trial, selected)
        results = [
            evaluate_window(strategy, portfolio, params, fold.validation_dates)
            for fold in folds
        ]
        results_by_trial[trial.number] = results
        fold_sharpes = np.asarray([result.sharpe for result in results], dtype=float)
        fold_trades = [result.metrics["num_trades"] for result in results]
        pooled = pooled_result(results)
        trial.set_user_attr(
            "fold_sharpes", [round(float(value), 6) for value in fold_sharpes]
        )
        trial.set_user_attr("fold_trades", fold_trades)
        trial.set_user_attr("pooled_sharpe", round(float(pooled.sharpe), 6))
        trial.set_user_attr("net_pnl_usd", pooled.metrics["net_pnl_usd"])
        if min(fold_trades) < min_fold_trades:
            return -1_000.0 + sum(fold_trades) / 10_000.0
        return float(
            pooled.sharpe - stability_penalty * np.std(fold_sharpes, ddof=0)
        )

    def progress(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        completed = trial.number + 1
        if completed == 1 or completed % 10 == 0 or completed == trials:
            print(
                f"    {completed}/{trials} trials; best={study.best_value:.4f}",
                flush=True,
            )

    study.optimize(objective, n_trials=trials, callbacks=[progress], gc_after_trial=True)
    best = suggest_guided(strategy, optuna.trial.FixedTrial(study.best_params), selected)
    return study, best, results_by_trial[study.best_trial.number]


def _fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, str):
        return value
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{digits}f}"


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
    records: dict[str, StrategyRecord],
    elapsed: float,
) -> None:
    lines = [
        "# SVM-Guided Optimization Across All Strategies",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Executive summary",
        "",
        "Each strategy used its own baseline trades, SVM ranking, three-parameter maximum, "
        "walk-forward study, and untouched holdout. No live configuration was changed.",
        "",
        "| Strategy | Selected parameters | SVM balanced accuracy | SVM ROC AUC | Walk-forward Sharpe | Holdout Sharpe | Decision |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for strategy, record in records.items():
        current_wf = pooled_result(record.baseline_folds)
        optimized_wf = pooled_result(record.optimized_folds)
        svm_reliable = (
            record.svm.metrics["balanced_accuracy"] >= 0.55
            and record.svm.metrics["roc_auc"] >= 0.55
        )
        holdout_improved = record.optimized_holdout.sharpe > record.baseline_holdout.sharpe
        decision = (
            "Promising; demo-test"
            if svm_reliable and holdout_improved
            else "Exploratory only"
            if holdout_improved
            else "Retain current"
        )
        lines.append(
            f"| {LABELS[strategy]} | {', '.join(f'`{p}`' for p in record.selected)} | "
            f"{record.svm.metrics['balanced_accuracy']:.3f} | "
            f"{record.svm.metrics['roc_auc']:.3f} | "
            f"{current_wf.sharpe:.3f} → {optimized_wf.sharpe:.3f} | "
            f"{record.baseline_holdout.sharpe:.3f} → {record.optimized_holdout.sharpe:.3f} | "
            f"{decision} |"
        )

    lines.extend([
        "",
        "## Method",
        "",
        f"- Final {args.lookback_days} calendar days; final {args.holdout_fraction:.0%} "
        "reserved before feature discovery.",
        f"- Linear-kernel, class-balanced SVM; first {args.svm_train_fraction:.0%} of "
        "development trades fit the model and the remainder measure permutation importance.",
        "- Features use information available by entry only. Positive validation permutation "
        "importance is mapped to an existing parameter; non-actionable context is ignored.",
        f"- At most {args.max_parameters} parameters per strategy enter Optuna; all others "
        "remain at current values.",
        f"- Optuna uses {args.folds} chronological forward windows, {args.trials} trials, "
        f"seed {args.seed}, and a {args.stability_penalty:g} fold-instability penalty.",
        "- The untouched holdout is evaluated only after SVM ranking and Optuna selection.",
        "",
    ])

    for strategy, record in records.items():
        current_wf = pooled_result(record.baseline_folds)
        optimized_wf = pooled_result(record.optimized_folds)
        lines.extend([
            f"## {LABELS[strategy]}",
            "",
            f"Development dates: {record.development_dates[0]} to {record.development_dates[-1]}. "
            f"Untouched holdout: {record.holdout_dates[0]} to {record.holdout_dates[-1]}.",
            "",
            f"SVM samples: {len(record.svm.train)} fit / {len(record.svm.validation)} validation.",
            "",
            "| SVM metric | Result |",
            "| --- | ---: |",
            f"| Accuracy | {_fmt(record.svm.metrics['accuracy'])} |",
            f"| Majority accuracy | {_fmt(record.svm.metrics['majority_accuracy'])} |",
            f"| Balanced accuracy | {_fmt(record.svm.metrics['balanced_accuracy'])} |",
            f"| ROC AUC | {_fmt(record.svm.metrics['roc_auc'])} |",
            "",
            "### Parameter ranking",
            "",
            "| Rank | Parameter | Score | Evidence | Selected |",
            "| ---: | --- | ---: | --- | --- |",
        ])
        for rank, (parameter, score, features) in enumerate(record.parameter_ranking, 1):
            lines.append(
                f"| {rank} | `{parameter}` | {score:.3f} | "
                f"{', '.join(f'`{feature}`' for feature in features)} | "
                f"{'yes' if parameter in record.selected else 'no'} |"
            )
        lines.extend([
            "",
            "Top ten baseline features by validation permutation importance:",
            "",
            "| Feature | Importance | Std. dev. |",
            "| --- | ---: | ---: |",
        ])
        for feature, mean, std in record.svm.permutation[:10]:
            lines.append(f"| `{feature}` | {mean:.3f} | {std:.3f} |")
        lines.extend([
            "",
            "### Backtest results",
            "",
            "| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            _result_row("Current / pooled walk-forward", current_wf),
            _result_row("Guided / pooled walk-forward", optimized_wf),
            _result_row("Current / untouched holdout", record.baseline_holdout),
            _result_row("Guided / untouched holdout", record.optimized_holdout),
            "",
            "| Fold | Current Sharpe | Guided Sharpe | Current trades | Guided trades |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ])
        for fold, current, optimized in zip(
            record.folds, record.baseline_folds, record.optimized_folds
        ):
            lines.append(
                f"| {fold.number} | {current.sharpe:.3f} | {optimized.sharpe:.3f} | "
                f"{current.metrics['num_trades']} | {optimized.metrics['num_trades']} |"
            )
        lines.extend([
            "",
            "Untouched holdout by symbol:",
            "",
            "| Symbol | Current Sharpe | Guided Sharpe | Current trades | Guided trades | Current net | Guided net |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for symbol in record.baseline_holdout.per_symbol:
            current = record.baseline_holdout.per_symbol[symbol]
            guided = record.optimized_holdout.per_symbol[symbol]
            lines.append(
                f"| {symbol} | {_fmt(current['sharpe'])} | {_fmt(guided['sharpe'])} | "
                f"{current['num_trades']} | {guided['num_trades']} | "
                f"${current['net_pnl_usd']:,.2f} | ${guided['net_pnl_usd']:,.2f} |"
            )
        lines.extend([
            "",
            "Selected full configuration:",
            "",
            "```json",
            json.dumps(record.best_params, indent=2, sort_keys=True),
            "```",
            "",
        ])

    lines.extend([
        "## Limitations",
        "",
        "SVM importance is associative, parameter mappings are hypotheses, and the number of "
        "baseline trades can be small. A favorable holdout can also be caused by one or two "
        "trades. Treat the holdout and per-symbol consistency as decisive, and forward-test any "
        "candidate before changing live settings.",
        "",
        f"Runtime: {elapsed:.1f} seconds.",
        "",
        "Reproduce from `backend/`:",
        "",
        "```powershell",
        f"python backtests/all_strategies_svm_guided_optuna.py --trials {args.trials} "
        f"--max-parameters {args.max_parameters} --lookback-days {args.lookback_days} "
        f"--seed {args.seed}",
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--max-parameters", type=int, default=3)
    parser.add_argument("--lookback-days", type=int, default=240)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--svm-train-fraction", type=float, default=0.70)
    parser.add_argument("--svm-permutation-repeats", type=int, default=50)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--initial-train-fraction", type=float, default=0.50)
    parser.add_argument("--min-fold-trades", type=int, default=2)
    parser.add_argument("--stability-penalty", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--strategies", nargs="+", choices=(*STRATEGIES, "all"), default=["all"]
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("ALL_STRATEGIES_SVM_GUIDED_REPORT.md"),
    )
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    if not 1 <= args.max_parameters <= 3:
        parser.error("--max-parameters must be between 1 and 3")
    if args.lookback_days < 60:
        parser.error("--lookback-days must be at least 60")
    if not 0.1 <= args.holdout_fraction <= 0.4:
        parser.error("--holdout-fraction must be between 0.1 and 0.4")
    if not 0.5 <= args.svm_train_fraction <= 0.85:
        parser.error("--svm-train-fraction must be between 0.5 and 0.85")
    if args.svm_permutation_repeats < 5:
        parser.error("--svm-permutation-repeats must be at least 5")
    if args.folds < 2:
        parser.error("--folds must be at least 2")
    if not 0.25 <= args.initial_train_fraction <= 0.75:
        parser.error("--initial-train-fraction must be between 0.25 and 0.75")
    if args.min_fold_trades < 1:
        parser.error("--min-fold-trades must be positive")
    if args.stability_penalty < 0:
        parser.error("--stability-penalty cannot be negative")
    return args


def run_strategy(
    strategy: str,
    args: argparse.Namespace,
    seed: int,
) -> StrategyRecord:
    print(f"\n{LABELS[strategy]}: loading data ...", flush=True)
    portfolio, dates = load_portfolio(strategy, args.data_dir, args.lookback_days)
    folds, development, holdout = make_folds(
        dates, args.holdout_fraction, args.folds, args.initial_train_fraction
    )
    dataset = baseline_dataset(strategy, portfolio, development)
    svm_result = fit_svm(
        strategy,
        dataset,
        args.svm_train_fraction,
        args.svm_permutation_repeats,
        seed,
    )
    selected, ranking = rank_parameters(
        strategy, svm_result.permutation, args.max_parameters
    )
    print(
        f"  baseline trades={len(dataset)}; SVM balanced accuracy="
        f"{svm_result.metrics['balanced_accuracy']:.3f}, AUC="
        f"{svm_result.metrics['roc_auc']:.3f}",
        flush=True,
    )
    print(f"  selected: {', '.join(selected)}", flush=True)
    baseline_folds = [
        evaluate_window(strategy, portfolio, current_params(strategy), fold.validation_dates)
        for fold in folds
    ]
    effective_min = min(args.min_fold_trades, max(1, min(
        result.metrics["num_trades"] for result in baseline_folds
    )))
    study, best_params, optimized_folds = optimize_guided(
        strategy,
        portfolio,
        folds,
        selected,
        args.trials,
        seed,
        effective_min,
        args.stability_penalty,
    )
    # The holdout is first run after both model-guided selection stages finish.
    baseline_holdout = evaluate_window(
        strategy, portfolio, current_params(strategy), holdout
    )
    optimized_holdout = (
        baseline_holdout
        if study.best_trial.number == 0
        else evaluate_window(strategy, portfolio, best_params, holdout)
    )
    print(
        f"  holdout Sharpe: {baseline_holdout.sharpe:.3f} -> "
        f"{optimized_holdout.sharpe:.3f}",
        flush=True,
    )
    return StrategyRecord(
        portfolio,
        folds,
        development,
        holdout,
        svm_result,
        ranking,
        selected,
        study,
        best_params,
        baseline_folds,
        optimized_folds,
        baseline_holdout,
        optimized_holdout,
    )


def main() -> int:
    args = parse_args()
    logging.disable(logging.CRITICAL)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    selected = list(STRATEGIES) if "all" in args.strategies else list(dict.fromkeys(args.strategies))
    started = time.perf_counter()
    records = {
        strategy: run_strategy(strategy, args, args.seed + offset)
        for offset, strategy in enumerate(selected)
    }
    elapsed = time.perf_counter() - started
    write_report(args.report.resolve(), args, records, elapsed)
    print(f"\nReport written to {args.report.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
