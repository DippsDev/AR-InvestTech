"""Explain Trendline wins/losses with a leakage-safe shallow decision tree.

The classifier uses only information known when a trade is filled. It trains on
the first chronological partition and is evaluated once on the later holdout.

Run from ``backend``::

    python backtests/trendline_decision_tree.py
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
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier, export_text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtests.optuna_sharpe import (  # noqa: E402
    DataBundle,
    _costs,
    _trendline_config,
    load_bundles,
)
from trendline.backtest import BacktestCosts, run_backtest  # noqa: E402


NUMERIC_FEATURES = [
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
    "line_anchor_span",
    "line_age",
    "directional_line_slope",
    "touch_gap_to_range",
    "hour_sin",
    "hour_cos",
    "weekday",
]
CATEGORICAL_FEATURES = ["symbol", "direction"]
FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES
MAX_DEPTH = 8
MIN_SAMPLES_LEAF = 8
FILTER_THRESHOLD = 0.60


@dataclass
class ModelResults:
    train: pd.DataFrame
    test: pd.DataFrame
    pipeline: Pipeline
    transformed_feature_names: list[str]
    rules: str
    cv_scores: np.ndarray
    metrics: dict[str, float]
    permutation: list[tuple[str, float, float]]


def _trade_rows(bundle: DataBundle, phase: str) -> list[dict[str, Any]]:
    frame = bundle.train_with_warmup if phase == "train" else bundle.test_with_warmup
    phase_start = bundle.train_start if phase == "train" else bundle.test_start
    config = _trendline_config(bundle, {})
    trades = run_backtest(frame, config, _costs(BacktestCosts, bundle.scale))
    trades = [trade for trade in trades if trade.entry_time >= phase_start]

    opens = frame["open"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    ranges = np.maximum(highs - lows, 1e-9)
    rows: list[dict[str, Any]] = []

    for trade in trades:
        i = int(trade.touch_bar)
        anchor1 = int(trade.line_anchor1_bar)
        anchor2 = int(trade.line_anchor2_bar)
        if i < 24 or not (0 <= anchor1 < anchor2 <= i):
            continue

        recent_range = ranges[i - 23:i + 1]
        avg_range = max(float(np.mean(recent_range)), 1e-9)
        candle_range = ranges[i]
        body = abs(closes[i] - opens[i])
        upper_wick = highs[i] - max(opens[i], closes[i])
        lower_wick = min(opens[i], closes[i]) - lows[i]
        direction_sign = 1.0 if trade.direction == "long" else -1.0

        line_prices = lows if trade.line_kind == "support" else highs
        anchor1_price = float(line_prices[anchor1])
        anchor2_price = float(line_prices[anchor2])
        slope = (anchor2_price - anchor1_price) / (anchor2 - anchor1)
        line_value = anchor1_price + slope * (i - anchor1)
        touch_price = lows[i] if trade.line_kind == "support" else highs[i]

        target1_r = abs(trade.target_price - trade.entry_price) / max(trade.risk_points, 1e-9)
        if trade.target_price_2 is not None:
            target2_r = abs(trade.target_price_2 - trade.entry_price) / max(trade.risk_points, 1e-9)
            planned_reward_r = trade.tp1_fraction * target1_r + (1.0 - trade.tp1_fraction) * target2_r
        else:
            planned_reward_r = target1_r

        returns = {
            horizon: closes[i] / closes[i - horizon] - 1.0
            for horizon in (1, 3, 6, 24)
        }
        prior_returns = np.diff(np.log(np.maximum(closes[i - 24:i + 1], 1e-9)))
        sma20 = float(np.mean(closes[i - 19:i + 1]))
        entry_hour = trade.entry_time.hour + trade.entry_time.minute / 60.0
        exit_timestamp = trade.exit_time if trade.exit_time is not None else trade.entry_time

        rows.append({
            "symbol": bundle.symbol,
            "direction": trade.direction,
            "risk_to_range": trade.risk_points / avg_range,
            "entry_gap_r": abs(trade.entry_price - closes[i]) / max(trade.risk_points, 1e-9),
            "planned_reward_r": planned_reward_r,
            "candle_range_vs_24h": candle_range / avg_range,
            "body_ratio": body / candle_range,
            "upper_wick_ratio": upper_wick / candle_range,
            "lower_wick_ratio": lower_wick / candle_range,
            "close_location": (closes[i] - lows[i]) / candle_range,
            "directional_candle_body": direction_sign * (closes[i] - opens[i]) / candle_range,
            "return_1h": returns[1],
            "return_3h": returns[3],
            "return_6h": returns[6],
            "return_24h": returns[24],
            "directional_return_6h": direction_sign * returns[6],
            "price_vs_sma20_range": (closes[i] - sma20) / avg_range,
            "return_volatility_24h": float(np.std(prior_returns, ddof=1)),
            "line_anchor_span": float(anchor2 - anchor1),
            "line_age": float(i - anchor2),
            "directional_line_slope": direction_sign * slope / avg_range,
            "touch_gap_to_range": abs(touch_price - line_value) / avg_range,
            "hour_sin": math.sin(2.0 * math.pi * entry_hour / 24.0),
            "hour_cos": math.cos(2.0 * math.pi * entry_hour / 24.0),
            "weekday": float(trade.entry_time.weekday()),
            "entry_time": trade.entry_time,
            "exit_date": exit_timestamp.date(),
            "pnl_usd": float(trade.pnl_dollars or 0.0),
            "won": int((trade.pnl_dollars or 0.0) > 0.0),
        })
    return rows


def build_dataset(bundles: list[DataBundle]) -> tuple[pd.DataFrame, pd.DataFrame]:
    train_rows: list[dict[str, Any]] = []
    test_rows: list[dict[str, Any]] = []
    for bundle in bundles:
        train_rows.extend(_trade_rows(bundle, "train"))
        test_rows.extend(_trade_rows(bundle, "test"))
    train = pd.DataFrame(train_rows).sort_values("entry_time").reset_index(drop=True)
    test = pd.DataFrame(test_rows).sort_values("entry_time").reset_index(drop=True)
    if train.empty or test.empty:
        raise RuntimeError("Trendline produced no trades on one side of the split")
    return train, test


def fit_model(train: pd.DataFrame, test: pd.DataFrame, seed: int) -> ModelResults:
    transformer = ColumnTransformer(
        [
            ("categorical", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
            ("numeric", "passthrough", NUMERIC_FEATURES),
        ],
        verbose_feature_names_out=False,
    )
    tree = DecisionTreeClassifier(
        max_depth=MAX_DEPTH,
        min_samples_leaf=MIN_SAMPLES_LEAF,
        class_weight="balanced",
        random_state=seed,
    )
    pipeline = Pipeline([("features", transformer), ("tree", tree)])
    x_train, y_train = train[FEATURES], train["won"]
    x_test, y_test = test[FEATURES], test["won"]

    split_count = min(4, max(2, len(train) // 15))
    cv = TimeSeriesSplit(n_splits=split_count)
    cv_scores = cross_val_score(pipeline, x_train, y_train, cv=cv, scoring="balanced_accuracy")
    pipeline.fit(x_train, y_train)
    predictions = pipeline.predict(x_test)
    probabilities = pipeline.predict_proba(x_test)[:, list(pipeline.classes_).index(1)]

    metrics = {
        "accuracy": accuracy_score(y_test, predictions),
        "balanced_accuracy": balanced_accuracy_score(y_test, predictions),
        "precision": precision_score(y_test, predictions, zero_division=0),
        "recall": recall_score(y_test, predictions, zero_division=0),
        "f1": f1_score(y_test, predictions, zero_division=0),
        "roc_auc": roc_auc_score(y_test, probabilities) if y_test.nunique() == 2 else float("nan"),
        "majority_accuracy": max(float(y_test.mean()), 1.0 - float(y_test.mean())),
    }
    tn, fp, fn, tp = confusion_matrix(y_test, predictions, labels=[0, 1]).ravel()
    metrics.update({"tn": float(tn), "fp": float(fp), "fn": float(fn), "tp": float(tp)})

    transformed_names = transformer.get_feature_names_out().tolist()
    rules = export_text(
        pipeline.named_steps["tree"],
        feature_names=transformed_names,
        decimals=3,
    )
    perm = permutation_importance(
        pipeline,
        x_test,
        y_test,
        scoring="balanced_accuracy",
        n_repeats=20,
        random_state=seed,
    )
    permutation = sorted(
        [
            (feature, float(mean), float(std))
            for feature, mean, std in zip(FEATURES, perm.importances_mean, perm.importances_std)
        ],
        key=lambda item: item[1],
        reverse=True,
    )

    test = test.copy()
    test["predicted_win"] = predictions
    test["win_probability"] = probabilities
    return ModelResults(train, test, pipeline, transformed_names, rules, cv_scores, metrics, permutation)


def _daily_sharpe(rows: pd.DataFrame, trading_dates: list[date]) -> float:
    if len(trading_dates) < 2:
        return 0.0
    daily = rows.groupby("exit_date")["pnl_usd"].sum().reindex(trading_dates, fill_value=0.0)
    std = float(daily.std(ddof=1))
    if not math.isfinite(std) or std <= 1e-12:
        return 0.0
    span = max((trading_dates[-1] - trading_dates[0]).days + 1, 1)
    periods_per_year = 365.25 * len(trading_dates) / span
    return float(daily.mean() / std * math.sqrt(periods_per_year))


def _trade_summary(rows: pd.DataFrame, trading_dates: list[date]) -> dict[str, float]:
    wins = rows.loc[rows["pnl_usd"] > 0, "pnl_usd"]
    losses = rows.loc[rows["pnl_usd"] <= 0, "pnl_usd"]
    gross_loss = abs(float(losses.sum()))
    gross_profit = float(wins.sum())
    return {
        "trades": float(len(rows)),
        "win_rate": float((rows["pnl_usd"] > 0).mean() * 100.0) if len(rows) else 0.0,
        "net_pnl": float(rows["pnl_usd"].sum()),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        "sharpe": _daily_sharpe(rows, trading_dates),
    }


def _fmt(value: float, digits: int = 3) -> str:
    if not math.isfinite(value):
        return "inf" if value > 0 else "n/a"
    return f"{value:.{digits}f}"


def _tree_importance(results: ModelResults) -> list[tuple[str, float]]:
    values = results.pipeline.named_steps["tree"].feature_importances_
    return sorted(
        [(name, float(value)) for name, value in zip(results.transformed_feature_names, values) if value > 0],
        key=lambda item: item[1],
        reverse=True,
    )


def write_report(
    path: Path,
    bundles: list[DataBundle],
    cutoff: date,
    results: ModelResults,
    args: argparse.Namespace,
    elapsed: float,
) -> None:
    train = results.train
    test = results.test
    all_test_dates = sorted({day for bundle in bundles for day in bundle.test_dates})
    selected = test.loc[test["win_probability"] >= FILTER_THRESHOLD].copy()
    all_summary = _trade_summary(test, all_test_dates)
    selected_summary = _trade_summary(selected, all_test_dates)
    tree_importance = _tree_importance(results)

    if results.metrics["balanced_accuracy"] < 0.55 or results.metrics["roc_auc"] < 0.55:
        conclusion = (
            "The tree does not generalize well enough to use as a live trade filter. "
            "Treat its splits as exploratory hypotheses only."
        )
    elif len(selected) < 10:
        conclusion = (
            "The holdout discrimination is promising, but the high-confidence subset is too small "
            "for a live rule. Gather more trades or repeat across walk-forward folds."
        )
    else:
        conclusion = (
            "The tree shows useful holdout discrimination, but it still needs repeated walk-forward "
            "validation and demo forward-testing before becoming a live filter."
        )

    lines = [
        "# Trendline Win/Loss Decision Tree",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Conclusion",
        "",
        conclusion,
        "",
        "## Experimental design",
        "",
        f"- Portfolio: {', '.join(bundle.symbol for bundle in bundles)} using the current live Trendline configuration.",
        f"- Data: final {args.lookback_days} common calendar days; chronological cutoff `{cutoff}`.",
        f"- Samples: {len(train)} training trades ({train['won'].mean() * 100:.1f}% winners), "
        f"{len(test)} holdout trades ({test['won'].mean() * 100:.1f}% winners).",
        f"- Model: class-balanced decision tree, max depth `{MAX_DEPTH}`, minimum `{MIN_SAMPLES_LEAF}` training trades per leaf, seed `{args.seed}`.",
        "- Every feature is available at signal close or next-bar fill. P/L, exit reason, exit time, future bars, and test labels are excluded from training features.",
        "- Training time-series cross-validation is diagnostic only; tree settings were fixed in advance and were not tuned against the holdout.",
        "",
        "## Holdout classification",
        "",
        "| Metric | Result |",
        "| --- | ---: |",
        f"| Accuracy | {_fmt(results.metrics['accuracy'])} |",
        f"| Majority-class accuracy | {_fmt(results.metrics['majority_accuracy'])} |",
        f"| Balanced accuracy | {_fmt(results.metrics['balanced_accuracy'])} |",
        f"| ROC AUC | {_fmt(results.metrics['roc_auc'])} |",
        f"| Winner precision | {_fmt(results.metrics['precision'])} |",
        f"| Winner recall | {_fmt(results.metrics['recall'])} |",
        f"| Winner F1 | {_fmt(results.metrics['f1'])} |",
        f"| Training time-series CV balanced accuracy | {_fmt(float(np.mean(results.cv_scores)))} ± {_fmt(float(np.std(results.cv_scores, ddof=1)))} |",
        "",
        "Confusion matrix (actual rows, predicted columns):",
        "",
        "|  | Predicted loss | Predicted win |",
        "| --- | ---: | ---: |",
        f"| Actual loss | {int(results.metrics['tn'])} | {int(results.metrics['fp'])} |",
        f"| Actual win | {int(results.metrics['fn'])} | {int(results.metrics['tp'])} |",
        "",
        "## Hypothetical holdout filter",
        "",
        f"A fixed predicted-win threshold of `{FILTER_THRESHOLD:.2f}` is shown for diagnosis; it was not selected on the test set.",
        "",
        "| Holdout trades | Trades | Win rate | Net P/L | Profit factor | Daily P/L Sharpe |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| All current Trendline trades | {int(all_summary['trades'])} | {all_summary['win_rate']:.1f}% | ${all_summary['net_pnl']:,.2f} | {_fmt(all_summary['profit_factor'], 2)} | {_fmt(all_summary['sharpe'])} |",
        f"| Tree probability ≥ {FILTER_THRESHOLD:.2f} | {int(selected_summary['trades'])} | {selected_summary['win_rate']:.1f}% | ${selected_summary['net_pnl']:,.2f} | {_fmt(selected_summary['profit_factor'], 2)} | {_fmt(selected_summary['sharpe'])} |",
        "",
        "## Learned decision rules",
        "",
        "The leaf values are class-weighted counts because the model balances winners and losers.",
        "",
        "```text",
        results.rules.rstrip(),
        "```",
        "",
        "## Feature evidence",
        "",
        "### Features used by the fitted tree",
        "",
        "| Feature | Tree importance | Training winner median | Training loser median |",
        "| --- | ---: | ---: | ---: |",
    ]
    for feature, importance in tree_importance:
        original = feature
        if original in train.columns and pd.api.types.is_numeric_dtype(train[original]):
            winner_median = _fmt(float(train.loc[train["won"] == 1, original].median()))
            loser_median = _fmt(float(train.loc[train["won"] == 0, original].median()))
        else:
            winner_median = "categorical"
            loser_median = "categorical"
        lines.append(f"| `{feature}` | {importance:.3f} | {winner_median} | {loser_median} |")

    lines.extend([
        "",
        "### Holdout permutation importance",
        "",
        "Positive values mean shuffling the feature reduced holdout balanced accuracy. With this small holdout, these estimates are noisy.",
        "",
        "| Feature | Mean importance | Std. dev. |",
        "| --- | ---: | ---: |",
    ])
    for feature, mean, std in results.permutation[:10]:
        lines.append(f"| `{feature}` | {mean:.3f} | {std:.3f} |")

    lines.extend([
        "",
        "## Feature definitions",
        "",
        "- `risk_to_range`: initial stop distance divided by the prior 24-hour average candle range.",
        "- `entry_gap_r`: next-bar fill movement away from the signal close, measured in initial R.",
        "- `directional_*`: positive means aligned with the trade direction; negative means opposed.",
        "- `line_anchor_span` / `line_age`: hours between anchors and from the newest anchor to the touch.",
        "- `touch_gap_to_range`: distance between the touched candle extreme and extrapolated trendline, normalized by recent range.",
        "- Returns, volatility, SMA distance, candle geometry, hour, weekday, symbol, and direction use only information known at entry.",
        "",
        "## Limitations",
        "",
        "This is association, not causation. The sample is small, the same broker-history cost model is reused, and the backtester tracks one open Trendline trade at a time even though the live configuration permits concurrent positions. A decision tree can find unstable thresholds easily; no live filter should be added without more trades, repeated walk-forward validation, and demo forward-testing.",
        "",
        f"Runtime: {elapsed:.1f} seconds.",
        "",
        "Reproduce from `backend/`:",
        "",
        "```powershell",
        f"python backtests/trendline_decision_tree.py --lookback-days {args.lookback_days} --train-fraction {args.train_fraction} --seed {args.seed}",
        "```",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=240)
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--report",
        type=Path,
        default=Path(__file__).with_name("TRENDLINE_DECISION_TREE_REPORT.md"),
    )
    args = parser.parse_args()
    if args.lookback_days < 60:
        parser.error("--lookback-days must be at least 60")
    if not 0.5 <= args.train_fraction <= 0.9:
        parser.error("--train-fraction must be between 0.5 and 0.9")
    return args


def main() -> int:
    args = parse_args()
    logging.disable(logging.CRITICAL)
    started = time.perf_counter()
    print("Loading current Trendline portfolio and chronological split ...", flush=True)
    bundles, cutoff = load_bundles("trendline", args.data_dir, args.train_fraction, args.lookback_days)
    print(f"  symbols={', '.join(bundle.symbol for bundle in bundles)}; holdout starts {cutoff}", flush=True)
    print("Replaying current strategy and extracting entry-time features ...", flush=True)
    train, test = build_dataset(bundles)
    print(f"  train={len(train)} trades; test={len(test)} trades", flush=True)
    results = fit_model(train, test, args.seed)
    elapsed = time.perf_counter() - started
    write_report(args.report.resolve(), bundles, cutoff, results, args, elapsed)
    print(
        f"Holdout balanced accuracy={results.metrics['balanced_accuracy']:.3f}; "
        f"ROC AUC={results.metrics['roc_auc']:.3f}",
        flush=True,
    )
    print(f"Report written to {args.report.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
