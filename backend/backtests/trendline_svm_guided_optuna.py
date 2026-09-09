"""Use a baseline-trade SVM to constrain Trendline walk-forward optimization.

The SVM sees only baseline trades from the development period. Permutation
importance is measured on a later internal validation slice, translated to
existing strategy parameters, and only the highest-ranked parameters are
given to Optuna. The final holdout is untouched by both stages.

Run from ``backend``::

    python backtests/trendline_svm_guided_optuna.py --trials 40
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
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

from backtests.optuna_sharpe import load_bundles  # noqa: E402
from backtests.trendline_decision_tree import (  # noqa: E402
    CATEGORICAL_FEATURES,
    FEATURES,
    NUMERIC_FEATURES,
    _trade_rows,
)
from backtests.trendline_walk_forward import (  # noqa: E402
    Fold,
    PreparedSymbol,
    WindowResult,
    baseline_params,
    evaluate_window,
    load_portfolio,
    make_folds,
    pooled_result,
)


# Each mapping is intentionally causal and narrow. For example, time-of-day or
# recent-return features may rank highly but cannot tune an existing Trendline
# parameter, so they are reported but not handed to Optuna.
PARAMETER_FEATURES: dict[str, tuple[str, ...]] = {
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
}


@dataclass
class SVMResult:
    train: pd.DataFrame
    validation: pd.DataFrame
    pipeline: Pipeline
    metrics: dict[str, float]
    permutation: list[tuple[str, float, float]]


def baseline_development_rows(bundles: list[Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for bundle in bundles:
        rows.extend(_trade_rows(bundle, "train"))
    frame = pd.DataFrame(rows).sort_values("entry_time").reset_index(drop=True)
    if frame.empty:
        raise RuntimeError("Baseline Trendline produced no development trades")
    return frame


def split_svm_rows(
    rows: pd.DataFrame,
    train_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    split = min(max(int(len(rows) * train_fraction), 1), len(rows) - 1)
    train = rows.iloc[:split].copy()
    validation = rows.iloc[split:].copy()
    if train["won"].nunique() < 2 or validation["won"].nunique() < 2:
        raise RuntimeError("Both SVM partitions need winning and losing baseline trades")
    return train, validation


def fit_svm(
    rows: pd.DataFrame,
    train_fraction: float,
    seed: int,
    repeats: int,
) -> SVMResult:
    train, validation = split_svm_rows(rows, train_fraction)
    transformer = ColumnTransformer(
        [
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ],
        verbose_feature_names_out=False,
    )
    svm = SVC(kernel="linear", C=0.25, class_weight="balanced")
    pipeline = Pipeline([("features", transformer), ("svm", svm)])
    pipeline.fit(train[FEATURES], train["won"])

    predictions = pipeline.predict(validation[FEATURES])
    decision = pipeline.decision_function(validation[FEATURES])
    majority = max(float(validation["won"].mean()), 1.0 - float(validation["won"].mean()))
    metrics = {
        "accuracy": accuracy_score(validation["won"], predictions),
        "balanced_accuracy": balanced_accuracy_score(validation["won"], predictions),
        "roc_auc": roc_auc_score(validation["won"], decision),
        "majority_accuracy": majority,
    }
    importance = permutation_importance(
        pipeline,
        validation[FEATURES],
        validation["won"],
        scoring="balanced_accuracy",
        n_repeats=repeats,
        random_state=seed,
    )
    permutation = sorted(
        [
            (feature, float(mean), float(std))
            for feature, mean, std in zip(
                FEATURES, importance.importances_mean, importance.importances_std
            )
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    return SVMResult(train, validation, pipeline, metrics, permutation)


def rank_parameters(
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
            for parameter, features in PARAMETER_FEATURES.items()
        ],
        key=lambda item: item[1],
        reverse=True,
    )
    selected = [parameter for parameter, score, _ in ranking if score > 0.0][:maximum]
    if not selected:
        raise RuntimeError("The SVM identified no positive actionable feature importance")
    return selected, ranking


def suggest_guided(trial: optuna.Trial, selected: list[str]) -> dict[str, Any]:
    params = baseline_params()
    if "swing_lookback" in selected:
        params["swing_lookback"] = trial.suggest_int("swing_lookback", 2, 5)
    if "steepness_max_ratio" in selected:
        params["steepness_max_ratio"] = trial.suggest_float(
            "steepness_max_ratio", 0.5, 1.5, step=0.25
        )
    if "touch_scale" in selected:
        params["touch_scale"] = trial.suggest_float("touch_scale", 0.6, 1.5, log=True)
    if "stop_buffer_scale" in selected:
        params["stop_buffer_scale"] = trial.suggest_float(
            "stop_buffer_scale", 0.7, 1.5, log=True
        )
    if "min_risk_scale" in selected:
        params["min_risk_scale"] = trial.suggest_float(
            "min_risk_scale", 0.7, 1.5, log=True
        )
    if "candle_body_ratio_max" in selected:
        params["candle_body_ratio_max"] = trial.suggest_float(
            "candle_body_ratio_max", 0.20, 0.40
        )
    if "candle_wick_ratio_min" in selected:
        params["candle_wick_ratio_min"] = trial.suggest_float(
            "candle_wick_ratio_min", 1.5, 3.0
        )
    return params


def optimize_guided(
    portfolio: list[PreparedSymbol],
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
    study = optuna.create_study(
        direction="maximize",
        sampler=sampler,
        study_name="trendline_svm_guided_walk_forward",
    )
    current = baseline_params()
    study.enqueue_trial({parameter: current[parameter] for parameter in selected})
    results_by_trial: dict[int, list[WindowResult]] = {}

    def objective(trial: optuna.Trial) -> float:
        params = suggest_guided(trial, selected)
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
        trial.set_user_attr("pooled_sharpe", round(float(pooled.sharpe), 6))
        trial.set_user_attr("net_pnl_usd", pooled.metrics["net_pnl_usd"])
        if min(trades) < min_fold_trades:
            return -1_000.0 + sum(trades) / 10_000.0
        return float(pooled.sharpe - stability_penalty * np.std(sharpes, ddof=0))

    def progress(study: optuna.Study, trial: optuna.trial.FrozenTrial) -> None:
        completed = trial.number + 1
        if completed == 1 or completed % 10 == 0 or completed == trials:
            print(
                f"  {completed}/{trials} trials; best adjusted Sharpe="
                f"{study.best_value:.4f}",
                flush=True,
            )

    study.optimize(objective, n_trials=trials, callbacks=[progress], gc_after_trial=True)
    best = suggest_guided(optuna.trial.FixedTrial(study.best_params), selected)
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
    svm_result: SVMResult,
    parameter_ranking: list[tuple[str, float, tuple[str, ...]]],
    selected: list[str],
    folds: list[Fold],
    study: optuna.Study,
    best_params: dict[str, Any],
    baseline_folds: list[WindowResult],
    optimized_folds: list[WindowResult],
    baseline_holdout: WindowResult,
    optimized_holdout: WindowResult,
    holdout_start: Any,
    elapsed: float,
) -> None:
    baseline_pooled = pooled_result(baseline_folds)
    optimized_pooled = pooled_result(optimized_folds)
    reliable = (
        svm_result.metrics["balanced_accuracy"] >= 0.55
        and svm_result.metrics["roc_auc"] >= 0.55
    )
    improved = optimized_holdout.sharpe > baseline_holdout.sharpe
    if not improved:
        recommendation = "Retain the current parameters; the guided candidate failed the untouched holdout."
    elif not reliable:
        recommendation = (
            "Do not promote automatically. The candidate improved the holdout, but the SVM's "
            "own validation discrimination was weak."
        )
    else:
        recommendation = (
            "The candidate is promising, but still requires demo forward-testing before promotion."
        )

    lines = [
        "# SVM-Guided Trendline Optimization Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Conclusion",
        "",
        recommendation,
        "",
        f"The SVM selected only **{len(selected)} parameters**: "
        + ", ".join(f"`{name}`" for name in selected)
        + ".",
        "",
        f"Walk-forward Sharpe: {_fmt(baseline_pooled.sharpe)} → "
        f"{_fmt(optimized_pooled.sharpe)}. Untouched holdout Sharpe: "
        f"{_fmt(baseline_holdout.sharpe)} → {_fmt(optimized_holdout.sharpe)}.",
        "",
        "## Experimental design",
        "",
        "- Stage 1: fit a class-balanced linear-kernel SVM to wins/losses from the "
        "baseline Trendline strategy.",
        f"- SVM samples: {len(svm_result.train)} early-development trades for fitting and "
        f"{len(svm_result.validation)} later-development trades for permutation importance.",
        "- Inputs contain only information available by entry. Exit outcome is the label; "
        "future-market features are excluded.",
        "- Only positive permutation importance from the later SVM validation slice counts. "
        "Non-actionable context such as symbol, hour, and returns is reported but cannot "
        "select a strategy parameter.",
        f"- Stage 2: optimize at most {args.max_parameters} mapped parameters over "
        f"{len(folds)} chronological forward windows using {args.trials} Optuna trials.",
        f"- Final holdout starts `{holdout_start}` and is untouched by SVM fitting, feature "
        "ranking, and Optuna selection.",
        "- Objective: pooled daily-P/L Sharpe minus "
        f"{args.stability_penalty:g} × fold-Sharpe standard deviation; every fold requires "
        f"at least {args.min_fold_trades} trades.",
        "- All unselected parameters remain exactly at the current baseline values.",
        "",
        "## SVM validation",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Accuracy | {_fmt(svm_result.metrics['accuracy'])} |",
        f"| Majority-class accuracy | {_fmt(svm_result.metrics['majority_accuracy'])} |",
        f"| Balanced accuracy | {_fmt(svm_result.metrics['balanced_accuracy'])} |",
        f"| ROC AUC | {_fmt(svm_result.metrics['roc_auc'])} |",
        "",
        "A model below roughly 0.55 balanced accuracy or ROC AUC has weak evidence for "
        "generalizable feature ranking; parameter selection should then be treated as exploratory.",
        "",
        "## Baseline feature importance",
        "",
        "Positive values mean that shuffling the feature reduced validation balanced accuracy.",
        "",
        "| Feature | Permutation importance | Std. dev. | Actionable mapping |",
        "| --- | ---: | ---: | --- |",
    ]
    feature_to_parameters: dict[str, list[str]] = {}
    for parameter, features in PARAMETER_FEATURES.items():
        for feature in features:
            feature_to_parameters.setdefault(feature, []).append(parameter)
    for feature, mean, std in svm_result.permutation:
        mapped = ", ".join(f"`{name}`" for name in feature_to_parameters.get(feature, []))
        lines.append(f"| `{feature}` | {mean:.3f} | {std:.3f} | {mapped or '—'} |")

    lines.extend([
        "",
        "## Parameter ranking",
        "",
        "A parameter score is the sum of positive validation permutation importance for "
        "its mapped baseline-trade features.",
        "",
        "| Rank | Parameter | Score | Evidence features | Selected |",
        "| ---: | --- | ---: | --- | --- |",
    ])
    for rank, (parameter, score, features) in enumerate(parameter_ranking, 1):
        lines.append(
            f"| {rank} | `{parameter}` | {score:.3f} | "
            f"{', '.join(f'`{feature}`' for feature in features)} | "
            f"{'yes' if parameter in selected else 'no'} |"
        )

    lines.extend([
        "",
        "## Optimization results",
        "",
        "| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        _result_row("Current / pooled walk-forward", baseline_pooled),
        _result_row("SVM-guided Optuna / pooled walk-forward", optimized_pooled),
        _result_row("Current / untouched holdout", baseline_holdout),
        _result_row("SVM-guided Optuna / untouched holdout", optimized_holdout),
        "",
        "### Forward folds",
        "",
        "| Fold | Current Sharpe | Guided Sharpe | Current trades | Guided trades |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ])
    for fold, current, optimized in zip(folds, baseline_folds, optimized_folds):
        lines.append(
            f"| {fold.number} | {_fmt(current.sharpe)} | {_fmt(optimized.sharpe)} | "
            f"{current.metrics['num_trades']} | {optimized.metrics['num_trades']} |"
        )

    lines.extend([
        "",
        "### Untouched holdout by symbol",
        "",
        "| Symbol | Current Sharpe | Guided Sharpe | Current trades | Guided trades | Current net | Guided net |",
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
        "## Selected configuration",
        "",
        "```json",
        json.dumps(best_params, indent=2, sort_keys=True),
        "```",
        "",
        "Only the selected keys above differ from—or were eligible to differ from—the baseline.",
        "",
        "## Top trials",
        "",
        "| Rank | Trial | Objective | Pooled Sharpe | Fold Sharpes | Fold trades | Parameters |",
        "| ---: | ---: | ---: | ---: | --- | --- | --- |",
    ])
    complete = [
        trial
        for trial in study.trials
        if trial.state == optuna.trial.TrialState.COMPLETE and trial.value is not None
    ]
    complete.sort(key=lambda trial: trial.value, reverse=True)
    for rank, trial in enumerate(complete[:10], 1):
        trial_params = json.dumps(trial.params, sort_keys=True).replace("|", "\\|")
        lines.append(
            f"| {rank} | {trial.number} | {trial.value:.3f} | "
            f"{trial.user_attrs.get('pooled_sharpe', 0):.3f} | "
            f"`{trial.user_attrs.get('fold_sharpes', [])}` | "
            f"`{trial.user_attrs.get('fold_trades', [])}` | `{trial_params}` |"
        )

    lines.extend([
        "",
        "## Limitations",
        "",
        "SVM importance is association, not a causal estimate of changing a parameter. "
        "The baseline sample is small, mapped features can be correlated, and Optuna still "
        "compares multiple alternatives. The final holdout therefore remains decisive; no "
        "candidate should be promoted from SVM importance alone.",
        "",
        f"Runtime: {elapsed:.1f} seconds.",
        "",
        "Reproduce from `backend/`:",
        "",
        "```powershell",
        f"python backtests/trendline_svm_guided_optuna.py --trials {args.trials} "
        f"--max-parameters {args.max_parameters} --lookback-days {args.lookback_days} "
        f"--seed {args.seed}",
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=40)
    parser.add_argument("--max-parameters", type=int, default=3)
    parser.add_argument("--lookback-days", type=int, default=240)
    parser.add_argument("--holdout-fraction", type=float, default=0.20)
    parser.add_argument("--svm-train-fraction", type=float, default=0.70)
    parser.add_argument("--svm-permutation-repeats", type=int, default=50)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--initial-train-fraction", type=float, default=0.50)
    parser.add_argument("--min-fold-trades", type=int, default=3)
    parser.add_argument("--stability-penalty", type=float, default=0.25)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("TRENDLINE_SVM_GUIDED_OPTUNA_REPORT.md"),
    )
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    if not 1 <= args.max_parameters <= len(PARAMETER_FEATURES):
        parser.error(f"--max-parameters must be between 1 and {len(PARAMETER_FEATURES)}")
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


def main() -> int:
    args = parse_args()
    logging.disable(logging.CRITICAL)
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    started = time.perf_counter()

    print("Loading baseline Trendline trades for SVM feature discovery ...", flush=True)
    bundles, cutoff = load_bundles(
        "trendline",
        args.data_dir,
        1.0 - args.holdout_fraction,
        args.lookback_days,
    )
    rows = baseline_development_rows(bundles)
    svm_result = fit_svm(
        rows,
        args.svm_train_fraction,
        args.seed,
        args.svm_permutation_repeats,
    )
    selected, parameter_ranking = rank_parameters(
        svm_result.permutation, args.max_parameters
    )
    print(
        f"  SVM validation: balanced accuracy="
        f"{svm_result.metrics['balanced_accuracy']:.4f}, "
        f"ROC AUC={svm_result.metrics['roc_auc']:.4f}",
        flush=True,
    )
    print(f"  selected parameters: {', '.join(selected)}", flush=True)

    portfolio, dates = load_portfolio(args.data_dir, args.lookback_days)
    folds, _, holdout_dates = make_folds(
        dates,
        args.holdout_fraction,
        args.folds,
        args.initial_train_fraction,
    )
    if cutoff != holdout_dates[0]:
        raise RuntimeError(
            f"SVM/optimizer holdout mismatch: {cutoff} != {holdout_dates[0]}"
        )
    baseline_folds = [
        evaluate_window(portfolio, baseline_params(), fold.validation_dates)
        for fold in folds
    ]
    study, best_params, optimized_folds = optimize_guided(
        portfolio,
        folds,
        selected,
        args.trials,
        args.seed,
        args.min_fold_trades,
        args.stability_penalty,
    )

    # Holdout outcomes are first computed after SVM selection and Optuna finish.
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
        svm_result,
        parameter_ranking,
        selected,
        folds,
        study,
        best_params,
        baseline_folds,
        optimized_folds,
        baseline_holdout,
        optimized_holdout,
        holdout_dates[0],
        elapsed,
    )
    print(
        f"  holdout Sharpe: current={baseline_holdout.sharpe:.4f}, "
        f"guided={optimized_holdout.sharpe:.4f}",
        flush=True,
    )
    print(f"Report written to {args.report.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
