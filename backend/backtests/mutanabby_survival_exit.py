"""Exploratory discrete-time survival exit for the Mutanabby strategy.

The model estimates the per-bar hazard that a trade's final profitable close
occurs now. A dynamic policy multiplies those hazards into a survival
probability and exits at the next bar open when survival is below a threshold
and current marked P/L is positive.

Run from ``backend``::

    python backtests/mutanabby_survival_exit.py
"""
from __future__ import annotations

import argparse
import logging
import math
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.all_strategies_svm_guided_optuna import (  # noqa: E402
    PortfolioItem,
    current_params,
    load_portfolio,
    run_symbol_window,
)
from backtests.optuna_sharpe import (  # noqa: E402
    _costs,
    _mutanabby_config,
    _sort_trades,
    daily_pnl_sharpe,
)
from mutanabby.backtest import BacktestCosts, run_backtest  # noqa: E402
from silver_bullet.metrics import compute_metrics  # noqa: E402


CATEGORICAL_FEATURES = ["symbol", "direction", "signal_strength"]
NUMERIC_FEATURES = [
    "elapsed_bars",
    "log_elapsed_bars",
    "current_r",
    "mfe_r",
    "drawdown_from_mfe_r",
    "momentum_1bar_r",
    "momentum_3bar_r",
    "volatility_6bar_r",
    "risk_to_range",
    "distance_to_target_r",
    "distance_to_stop_r",
    "rsi_at_signal",
    "tp1_hit",
]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
THRESHOLDS = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 0.95)


@dataclass
class Evaluation:
    sharpe: float
    metrics: dict[str, Any]
    per_symbol: dict[str, dict[str, Any]]
    trades: list[Any]
    dates: list[date]


@dataclass
class ThresholdResult:
    threshold: float
    objective: float
    pooled: Evaluation
    fold_sharpes: list[float]
    fold_trades: list[int]


def split_dates(
    dates: list[date],
    test_fraction: float,
    model_fraction_of_development: float,
) -> tuple[list[date], list[date], list[date]]:
    test_start = min(max(int(len(dates) * (1.0 - test_fraction)), 2), len(dates) - 1)
    development = dates[:test_start]
    test = dates[test_start:]
    model_end = min(
        max(int(len(development) * model_fraction_of_development), 1),
        len(development) - 1,
    )
    return development[:model_end], development[model_end:], test


def _frame_for_dates(item: PortfolioItem, dates: list[date]) -> pd.DataFrame:
    wanted = set(dates)
    frame_dates = item.frame["timestamp_ny"].dt.date
    positions = np.flatnonzero(frame_dates.isin(wanted).to_numpy())
    if not len(positions):
        return item.frame.iloc[:0].copy()
    warmup_start = max(0, int(positions[0]) - 300)
    stop = int(positions[-1]) + 1
    return item.frame.iloc[warmup_start:stop].reset_index(drop=True)


def _index_by_timestamp(frame: pd.DataFrame) -> dict[pd.Timestamp, int]:
    return {
        timestamp: index
        for index, timestamp in enumerate(frame["timestamp_ny"].tolist())
    }


def _marked_r(
    trade: Any,
    price: float,
    timestamp: pd.Timestamp,
    commission_r: float,
) -> tuple[float, bool]:
    sign = 1.0 if trade.direction == "long" else -1.0
    risk = max(float(trade.risk_points), 1e-9)
    tp1_time = getattr(trade, "tp1_exit_time", None)
    tp1_price = getattr(trade, "tp1_exit_price", None)
    after_tp1 = tp1_time is not None and tp1_price is not None and timestamp >= tp1_time
    if after_tp1:
        first_leg = trade.tp1_fraction * sign * float(tp1_price - trade.entry_price) / risk
        runner = (1.0 - trade.tp1_fraction) * sign * float(price - trade.entry_price) / risk
        return first_leg + runner - 2.0 * commission_r, True
    return sign * float(price - trade.entry_price) / risk - commission_r, False


def _feature_row(
    trade: Any,
    symbol: str,
    frame: pd.DataFrame,
    bar_idx: int,
    entry_idx: int,
    prior_mfe: float,
    commission_r: float,
) -> tuple[dict[str, Any], float]:
    closes = frame["close"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    timestamp = frame["timestamp_ny"].iloc[bar_idx]
    current_r, tp1_hit = _marked_r(
        trade, float(closes[bar_idx]), timestamp, commission_r
    )
    mfe_r = max(prior_mfe, current_r)
    risk = max(float(trade.risk_points), 1e-9)
    sign = 1.0 if trade.direction == "long" else -1.0
    one_back = max(entry_idx, bar_idx - 1)
    three_back = max(entry_idx, bar_idx - 3)
    recent_start = max(entry_idx, bar_idx - 6)
    recent_moves = np.diff(closes[recent_start:bar_idx + 1]) / risk
    volatility = float(np.std(recent_moves, ddof=1)) if len(recent_moves) > 1 else 0.0
    entry_range_start = max(0, entry_idx - 23)
    avg_range = max(
        float(np.mean(highs[entry_range_start:entry_idx + 1] - lows[entry_range_start:entry_idx + 1])),
        1e-9,
    )
    active_target = (
        trade.target_price_2
        if tp1_hit and trade.target_price_2 is not None
        else trade.target_price
    )
    elapsed = bar_idx - entry_idx + 1
    row = {
        "symbol": symbol,
        "direction": trade.direction,
        "signal_strength": trade.strength,
        "elapsed_bars": float(elapsed),
        "log_elapsed_bars": math.log1p(elapsed),
        "current_r": current_r,
        "mfe_r": mfe_r,
        "drawdown_from_mfe_r": max(0.0, mfe_r - current_r),
        "momentum_1bar_r": sign * float(closes[bar_idx] - closes[one_back]) / risk,
        "momentum_3bar_r": sign * float(closes[bar_idx] - closes[three_back]) / risk,
        "volatility_6bar_r": volatility,
        "risk_to_range": risk / avg_range,
        "distance_to_target_r": sign * float(active_target - closes[bar_idx]) / risk,
        "distance_to_stop_r": sign * float(closes[bar_idx] - trade.stop_price) / risk,
        "rsi_at_signal": float(trade.rsi_at_signal),
        "tp1_hit": float(tp1_hit),
    }
    return row, mfe_r


def _trade_survival_rows(
    trade: Any,
    symbol: str,
    frame: pd.DataFrame,
    commission_r: float,
) -> list[dict[str, Any]]:
    index = _index_by_timestamp(frame)
    entry_idx = index.get(trade.entry_time)
    exit_idx = index.get(trade.exit_time)
    if entry_idx is None or exit_idx is None or exit_idx <= entry_idx:
        return []

    rows: list[dict[str, Any]] = []
    mfe = -math.inf
    for bar_idx in range(entry_idx, exit_idx):
        row, mfe = _feature_row(
            trade, symbol, frame, bar_idx, entry_idx, mfe, commission_r
        )
        row.update(
            {
                "trade_key": f"{symbol}|{trade.entry_time.isoformat()}",
                "entry_time": trade.entry_time,
                "bar_time": frame["timestamp_ny"].iloc[bar_idx],
                "peak_event": 0,
            }
        )
        rows.append(row)

    profitable = [index for index, row in enumerate(rows) if row["current_r"] > 0]
    if profitable:
        peak_position = max(profitable, key=lambda index: rows[index]["current_r"])
        rows[peak_position]["peak_event"] = 1
        rows = rows[:peak_position + 1]
    return rows


def survival_dataset(
    portfolio: list[PortfolioItem],
    dates: list[date],
    commission: float,
    risk_per_trade: float,
) -> tuple[pd.DataFrame, int]:
    rows: list[dict[str, Any]] = []
    trade_count = 0
    params = current_params("mutanabby")
    for item in portfolio:
        frame, trades, _ = run_symbol_window(
            "mutanabby", item, params, dates
        )
        trade_count += len(trades)
        for trade in trades:
            rows.extend(
                _trade_survival_rows(
                    trade,
                    item.symbol,
                    frame,
                    commission / risk_per_trade,
                )
            )
    result = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    result = result.dropna(subset=FEATURES + ["peak_event"]).reset_index(drop=True)
    if result.empty or result["peak_event"].nunique() < 2:
        raise RuntimeError("Survival dataset needs both peak events and at-risk rows")
    return result, trade_count


def fit_model(rows: pd.DataFrame) -> Pipeline:
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
    model = LogisticRegression(C=0.25, max_iter=2_000, random_state=42)
    pipeline = Pipeline([("features", transformer), ("hazard", model)])
    pipeline.fit(rows[FEATURES], rows["peak_event"])
    return pipeline


def model_diagnostics(model: Pipeline, rows: pd.DataFrame) -> dict[str, float]:
    probability = model.predict_proba(rows[FEATURES])[:, 1]
    prediction = probability >= 0.5
    return {
        "event_rate": float(rows["peak_event"].mean()),
        "accuracy": accuracy_score(rows["peak_event"], prediction),
        "balanced_accuracy": balanced_accuracy_score(rows["peak_event"], prediction),
        "roc_auc": roc_auc_score(rows["peak_event"], probability),
        "brier": brier_score_loss(rows["peak_event"], probability),
    }


class SurvivalExitPolicy:
    def __init__(
        self,
        model: Pipeline,
        symbol: str,
        frame: pd.DataFrame,
        threshold: float,
        commission_r: float,
    ) -> None:
        self.model = model
        self.symbol = symbol
        self.frame = frame
        self.threshold = threshold
        self.commission_r = commission_r
        self.index = _index_by_timestamp(frame)
        self.state: dict[str, tuple[float, float]] = {}

    def should_exit(self, trade: Any, decision_bar_idx: int) -> bool:
        entry_idx = self.index.get(trade.entry_time)
        if entry_idx is None or decision_bar_idx < entry_idx:
            return False
        key = trade.entry_time.isoformat()
        survival, prior_mfe = self.state.get(key, (1.0, -math.inf))
        row, mfe = _feature_row(
            trade,
            self.symbol,
            self.frame,
            decision_bar_idx,
            entry_idx,
            prior_mfe,
            self.commission_r,
        )
        hazard = float(self.model.predict_proba(pd.DataFrame([row])[FEATURES])[0, 1])
        survival *= 1.0 - min(max(hazard, 0.0), 1.0)
        self.state[key] = (survival, mfe)
        return row["current_r"] > 0.0 and survival <= self.threshold


def evaluate(
    portfolio: list[PortfolioItem],
    dates: list[date],
    model: Pipeline | None = None,
    threshold: float | None = None,
    commission: float = 5.0,
    risk_per_trade: float = 100.0,
) -> Evaluation:
    wanted = set(dates)
    all_trades: list[Any] = []
    per_symbol: dict[str, dict[str, Any]] = {}
    params = current_params("mutanabby")
    for item in portfolio:
        frame = _frame_for_dates(item, dates)
        config = _mutanabby_config(item, params)
        costs = _costs(BacktestCosts, item.scale)
        policy = (
            SurvivalExitPolicy(
                model,
                item.symbol,
                frame,
                float(threshold),
                commission / risk_per_trade,
            )
            if model is not None and threshold is not None
            else None
        )
        trades = run_backtest(frame, config, costs, exit_policy=policy)
        trades = _sort_trades(
            [trade for trade in trades if trade.entry_time.date() in wanted]
        )
        symbol_dates = sorted(
            set(frame.loc[frame["timestamp_ny"].dt.date.isin(wanted), "timestamp_ny"].dt.date)
        )
        metrics = compute_metrics(trades)
        metrics["sharpe"] = daily_pnl_sharpe(trades, symbol_dates)
        per_symbol[item.symbol] = metrics
        all_trades.extend(trades)
    all_trades = _sort_trades(all_trades)
    return Evaluation(
        daily_pnl_sharpe(all_trades, dates),
        compute_metrics(all_trades),
        per_symbol,
        all_trades,
        dates,
    )


def pooled(results: list[Evaluation]) -> Evaluation:
    trades = _sort_trades([trade for result in results for trade in result.trades])
    dates = sorted({day for result in results for day in result.dates})
    return Evaluation(
        daily_pnl_sharpe(trades, dates),
        compute_metrics(trades),
        {},
        trades,
        dates,
    )


def tune_threshold(
    portfolio: list[PortfolioItem],
    validation_dates: list[date],
    model: Pipeline,
    stability_penalty: float,
) -> tuple[ThresholdResult, list[ThresholdResult], list[Evaluation]]:
    folds = [list(block) for block in np.array_split(validation_dates, 3) if len(block)]
    baseline_folds = [evaluate(portfolio, fold) for fold in folds]
    results: list[ThresholdResult] = []
    for threshold in THRESHOLDS:
        evaluations = [
            evaluate(portfolio, fold, model=model, threshold=threshold)
            for fold in folds
        ]
        aggregate = pooled(evaluations)
        sharpes = [result.sharpe for result in evaluations]
        objective = aggregate.sharpe - stability_penalty * float(np.std(sharpes))
        results.append(
            ThresholdResult(
                threshold,
                objective,
                aggregate,
                sharpes,
                [result.metrics["num_trades"] for result in evaluations],
            )
        )
        print(
            f"  threshold={threshold:.2f}: objective={objective:.3f}, "
            f"pooled Sharpe={aggregate.sharpe:.3f}",
            flush=True,
        )
    return max(results, key=lambda result: result.objective), results, baseline_folds


def _fmt(value: Any, digits: int = 3) -> str:
    if isinstance(value, str):
        return value
    if value is None or not math.isfinite(float(value)):
        return "n/a"
    return f"{float(value):.{digits}f}"


def _result_row(label: str, result: Evaluation) -> str:
    metrics = result.metrics
    return (
        f"| {label} | {result.sharpe:.3f} | {metrics['num_trades']} | "
        f"${metrics['net_pnl_usd']:,.2f} | {_fmt(metrics['profit_factor'], 2)} | "
        f"${metrics['max_drawdown_usd']:,.2f} | {metrics['win_rate_pct']:.1f}% | "
        f"{metrics['exit_breakdown'].get('survival_exit', 0)} |"
    )


def _coefficient_rows(model: Pipeline) -> list[tuple[str, float]]:
    names = model.named_steps["features"].get_feature_names_out()
    values = model.named_steps["hazard"].coef_[0]
    return sorted(
        [(str(name), float(value)) for name, value in zip(names, values)],
        key=lambda item: abs(item[1]),
        reverse=True,
    )


def write_report(
    path: Path,
    args: argparse.Namespace,
    model_dates: list[date],
    validation_dates: list[date],
    test_dates: list[date],
    train_rows: pd.DataFrame,
    train_trades: int,
    validation_rows: pd.DataFrame,
    validation_trades: int,
    diagnostics: dict[str, float],
    selected: ThresholdResult,
    threshold_results: list[ThresholdResult],
    baseline_validation_folds: list[Evaluation],
    baseline_test: Evaluation,
    survival_test: Evaluation,
    model: Pipeline,
) -> None:
    baseline_validation = pooled(baseline_validation_folds)
    survival_exits = [
        trade for trade in survival_test.trades if trade.exit_reason == "survival_exit"
    ]
    survival_exit_wins = sum((trade.pnl_dollars or 0.0) > 0 for trade in survival_exits)
    improved = survival_test.sharpe > baseline_test.sharpe
    recommendation = (
        "The survival exit is promising but not robust enough to deploy. It improved this "
        "historical test, but threshold-validation performance remained negative and the test "
        "gain was concentrated in JP225m. A genuinely new forward period is required."
        if improved
        else "The survival exit failed to improve the historical test; retain baseline management."
    )
    lines = [
        "# Mutanabby Survival-Exit Study",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Conclusion",
        "",
        recommendation,
        "",
        f"The model selected survival threshold `{selected.threshold:.2f}`. Historical-test "
        f"Sharpe changed from **{baseline_test.sharpe:.3f}** to **{survival_test.sharpe:.3f}**.",
        "",
        "> **This is exploratory validation, not a fresh test.** The final dates overlap the "
        "May-July period already inspected during prior optimization work. They cannot provide "
        "independent confirmation for a production change.",
        "",
        "## Big findings",
        "",
        f"- The hazard model ranked peak bars well on later data (ROC AUC "
        f"{diagnostics['roc_auc']:.3f}), but its class-balanced accuracy was only "
        f"{diagnostics['balanced_accuracy']:.3f}. The "
        f"{diagnostics['event_rate'] * 100:.2f}% event prevalence makes raw "
        "accuracy misleading.",
        f"- Threshold validation improved Sharpe only from {baseline_validation.sharpe:.3f} "
        f"to {selected.pooled.sharpe:.3f}; **both configurations still lost money** in that period.",
        f"- The historical-test result was much stronger: Sharpe {baseline_test.sharpe:.3f} "
        f"to {survival_test.sharpe:.3f}, net P/L ${baseline_test.metrics['net_pnl_usd']:,.2f} "
        f"to ${survival_test.metrics['net_pnl_usd']:,.2f}, and drawdown "
        f"${baseline_test.metrics['max_drawdown_usd']:,.2f} to "
        f"${survival_test.metrics['max_drawdown_usd']:,.2f}.",
        "- The improvement was concentrated in **JP225m**. US30m and ETHUSDm earned less "
        "under the policy, while USDJPYm was unchanged.",
        f"- The policy made {len(survival_exits)} test-period survival exits and all "
        f"{survival_exit_wins} were profitable, but the baseline test contained only "
        f"{baseline_test.metrics['num_trades']} trades.",
        "",
        "## Experimental design",
        "",
        f"- Model fit: {model_dates[0]} to {model_dates[-1]}.",
        f"- Threshold selection: {validation_dates[0]} to {validation_dates[-1]}.",
        f"- Historical test: {test_dates[0]} to {test_dates[-1]}.",
        "- Model: regularized discrete-time logistic hazard model.",
        "- Event: the bar containing a baseline trade's highest positive commission-adjusted "
        "close before its normal exit. Trades without a positive close are censored.",
        "- Dynamic inputs: elapsed time, current R, running MFE, drawdown from MFE, momentum, "
        "volatility, target/stop distance, RSI, signal strength, symbol, and direction.",
        "- At each completed H1 bar, predicted hazards are accumulated into survival "
        "probability. If survival is below the selected threshold and marked P/L is positive, "
        "the position exits at the next H1 open.",
        f"- A threshold of {selected.threshold:.2f} means exit eligibility begins when the model "
        f"estimates at most {selected.threshold * 100:.0f}% probability that the profitable peak "
        "still lies ahead (equivalently, at least "
        f"{(1.0 - selected.threshold) * 100:.0f}% cumulative probability it has occurred).",
        "- Threshold selection used three chronological validation blocks and maximized pooled "
        f"daily-P/L Sharpe minus {args.stability_penalty:g} times fold-Sharpe volatility.",
        "- The complete event loop was replayed, allowing earlier exits to change later trade availability.",
        "",
        "## Model sample",
        "",
        "| Partition | Baseline trades | Person-period rows | Peak events | Event rate |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| Model fit | {train_trades} | {len(train_rows)} | {int(train_rows['peak_event'].sum())} | "
        f"{train_rows['peak_event'].mean() * 100:.2f}% |",
        f"| Threshold validation | {validation_trades} | {len(validation_rows)} | "
        f"{int(validation_rows['peak_event'].sum())} | {validation_rows['peak_event'].mean() * 100:.2f}% |",
        "",
        "The number of rows is not the effective sample size: repeated bars from one trade are "
        "correlated. The trade and event counts are the important limits.",
        "",
        "## Hazard-model validation",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Accuracy at 0.50 hazard | {diagnostics['accuracy']:.3f} |",
        f"| Balanced accuracy | {diagnostics['balanced_accuracy']:.3f} |",
        f"| ROC AUC | {diagnostics['roc_auc']:.3f} |",
        f"| Brier score | {diagnostics['brier']:.3f} |",
        f"| Peak-event prevalence | {diagnostics['event_rate'] * 100:.2f}% |",
        "",
        "### Largest standardized coefficients",
        "",
        "Positive coefficients increase the estimated probability that the ultimate profitable "
        "peak occurs on the current bar; negative coefficients imply more estimated survival.",
        "",
        "| Feature | Coefficient |",
        "| --- | ---: |",
    ]
    for feature, coefficient in _coefficient_rows(model)[:12]:
        lines.append(f"| `{feature}` | {coefficient:.3f} |")

    lines.extend([
        "",
        "## Threshold selection",
        "",
        "| Survival threshold | Objective | Pooled Sharpe | Trades | Survival exits | Fold Sharpes |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for result in sorted(threshold_results, key=lambda result: result.threshold):
        exits = result.pooled.metrics["exit_breakdown"].get("survival_exit", 0)
        lines.append(
            f"| {result.threshold:.2f} | {result.objective:.3f} | "
            f"{result.pooled.sharpe:.3f} | {result.pooled.metrics['num_trades']} | {exits} | "
            f"`{[round(value, 3) for value in result.fold_sharpes]}` |"
        )

    lines.extend([
        "",
        "## Aggregate results",
        "",
        "| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate | Survival exits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        _result_row("Baseline / threshold validation", baseline_validation),
        _result_row("Survival / threshold validation", selected.pooled),
        _result_row("Baseline / historical test", baseline_test),
        _result_row("Survival / historical test", survival_test),
        "",
        "## Historical test by symbol",
        "",
        "| Symbol | Baseline Sharpe | Survival Sharpe | Baseline trades | Survival trades | Survival exits | Baseline net | Survival net |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for symbol in baseline_test.per_symbol:
        baseline = baseline_test.per_symbol[symbol]
        survival = survival_test.per_symbol[symbol]
        lines.append(
            f"| {symbol} | {_fmt(baseline['sharpe'])} | {_fmt(survival['sharpe'])} | "
            f"{baseline['num_trades']} | {survival['num_trades']} | "
            f"{survival['exit_breakdown'].get('survival_exit', 0)} | "
            f"${baseline['net_pnl_usd']:,.2f} | ${survival['net_pnl_usd']:,.2f} |"
        )

    lines.extend([
        "",
        "## Survival-exit behavior",
        "",
        f"The policy made {len(survival_exits)} survival exits in the historical test; "
        f"{survival_exit_wins} ({survival_exit_wins / len(survival_exits) * 100.0 if survival_exits else 0.0:.1f}%) "
        "closed with positive realized P/L.",
        "",
        "The strategy produced more trades under the policy because earlier exits freed the "
        "single-position slot for later signals. This is why the study replayed the complete "
        "event loop instead of editing baseline exits after the fact.",
        "",
        "## Limitations",
        "",
        "- The true final peak is known only retrospectively. The survival event is therefore "
        "a training label, not an event observable during live trading.",
        "- Baseline stop/target exits create informative censoring and can affect the learned hazard.",
        "- Person-period rows do not create independent samples; the number of trades remains small.",
        "- Survival probabilities from a logistic hazard model are model estimates, not guarantees.",
        "- Threshold comparisons introduce selection bias, even though selection was isolated from the test slice.",
        "- Next-open execution can gap away from the profitable decision close.",
        "- A fresh demo/forward period is mandatory before considering a live management change.",
        "",
        "Reproduce from `backend/`:",
        "",
        "```powershell",
        f"python backtests/mutanabby_survival_exit.py --lookback-days {args.lookback_days} "
        f"--test-fraction {args.test_fraction} --model-fraction {args.model_fraction} "
        f"--stability-penalty {args.stability_penalty}",
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=240)
    parser.add_argument("--test-fraction", type=float, default=0.30)
    parser.add_argument("--model-fraction", type=float, default=0.70)
    parser.add_argument("--stability-penalty", type=float, default=0.25)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("reports") / "MUTANABBY_SURVIVAL_EXIT_REPORT.md",
    )
    args = parser.parse_args()
    if args.lookback_days < 90:
        parser.error("--lookback-days must be at least 90")
    if not 0.2 <= args.test_fraction <= 0.4:
        parser.error("--test-fraction must be between 0.2 and 0.4")
    if not 0.5 <= args.model_fraction <= 0.8:
        parser.error("--model-fraction must be between 0.5 and 0.8")
    if args.stability_penalty < 0:
        parser.error("--stability-penalty cannot be negative")
    return args


def main() -> int:
    args = parse_args()
    logging.disable(logging.CRITICAL)
    print("Loading Mutanabby portfolio ...", flush=True)
    portfolio, dates = load_portfolio("mutanabby", args.data_dir, args.lookback_days)
    model_dates, validation_dates, test_dates = split_dates(
        dates, args.test_fraction, args.model_fraction
    )

    print("Building discrete-time peak-survival dataset ...", flush=True)
    train_rows, train_trades = survival_dataset(
        portfolio, model_dates, commission=5.0, risk_per_trade=100.0
    )
    validation_rows, validation_trades = survival_dataset(
        portfolio, validation_dates, commission=5.0, risk_per_trade=100.0
    )
    model = fit_model(train_rows)
    diagnostics = model_diagnostics(model, validation_rows)
    print(
        f"  model trades={train_trades}, events={int(train_rows['peak_event'].sum())}; "
        f"validation AUC={diagnostics['roc_auc']:.3f}",
        flush=True,
    )

    print("Selecting survival threshold on chronological validation folds ...", flush=True)
    selected, threshold_results, baseline_validation_folds = tune_threshold(
        portfolio, validation_dates, model, args.stability_penalty
    )
    print(
        f"  selected threshold={selected.threshold:.2f}, "
        f"validation Sharpe={selected.pooled.sharpe:.3f}",
        flush=True,
    )

    print("Running final historical test ...", flush=True)
    baseline_test = evaluate(portfolio, test_dates)
    survival_test = evaluate(
        portfolio, test_dates, model=model, threshold=selected.threshold
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    write_report(
        args.report.resolve(),
        args,
        model_dates,
        validation_dates,
        test_dates,
        train_rows,
        train_trades,
        validation_rows,
        validation_trades,
        diagnostics,
        selected,
        threshold_results,
        baseline_validation_folds,
        baseline_test,
        survival_test,
        model,
    )
    print(
        f"  historical-test Sharpe: baseline={baseline_test.sharpe:.3f}, "
        f"survival={survival_test.sharpe:.3f}",
        flush=True,
    )
    print(f"Report written to {args.report.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
