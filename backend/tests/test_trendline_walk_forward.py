from datetime import date, timedelta

import optuna
import pytest

from backtests.all_strategies_svm_guided_optuna import (
    current_params as all_current_params,
    feature_names as all_feature_names,
    suggest_guided as all_suggest_guided,
)
from backtests.trendline_svm_guided_optuna import rank_parameters, suggest_guided
from backtests.trendline_walk_forward import make_folds


def test_walk_forward_folds_expand_without_touching_holdout():
    start = date(2025, 1, 1)
    dates = [start + timedelta(days=offset) for offset in range(100)]

    folds, development, holdout = make_folds(
        dates,
        holdout_fraction=0.20,
        folds=4,
        initial_train_fraction=0.50,
    )

    assert len(development) == 80
    assert len(holdout) == 20
    assert [len(fold.train_dates) for fold in folds] == [40, 50, 60, 70]
    assert [len(fold.validation_dates) for fold in folds] == [10, 10, 10, 10]
    assert all(
        fold.train_dates[-1] < fold.validation_dates[0]
        for fold in folds
    )
    assert folds[-1].validation_dates[-1] < holdout[0]


def test_svm_parameter_ranking_is_positive_and_capped():
    permutation = [
        ("line_anchor_span", 0.20, 0.01),
        ("line_age", -0.10, 0.01),
        ("body_ratio", 0.15, 0.02),
        ("directional_candle_body", 0.10, 0.02),
        ("close_location", 0.05, 0.02),
    ]

    selected, ranking = rank_parameters(permutation, maximum=2)

    assert selected == ["candle_body_ratio_max", "swing_lookback"]
    assert ranking[0][1] == pytest.approx(0.30)
    assert ranking[1][1] == pytest.approx(0.20)


def test_guided_suggestion_keeps_unselected_parameters_at_baseline():
    params = suggest_guided(
        optuna.trial.FixedTrial({"swing_lookback": 5}),
        ["swing_lookback"],
    )

    assert params["swing_lookback"] == 5
    assert params["candle_body_ratio_max"] == 0.3
    assert params["touch_scale"] == 1.0


def test_cross_strategy_features_include_strategy_context():
    sb_categorical, sb_numeric, _ = all_feature_names("silver_bullet")
    mb_categorical, mb_numeric, _ = all_feature_names("mutanabby")

    assert "window" in sb_categorical
    assert "fvg_size_to_range" in sb_numeric
    assert "signal_strength" in mb_categorical
    assert "supertrend_gap_to_range" in mb_numeric


def test_cross_strategy_guidance_changes_only_selected_parameters():
    baseline = all_current_params("mutanabby")
    params = all_suggest_guided(
        "mutanabby",
        optuna.trial.FixedTrial({"risk_atr_length": 21}),
        ["risk_atr_length"],
    )

    assert params["risk_atr_length"] == 21
    assert params["sensitivity"] == baseline["sensitivity"]
    assert params["atr_risk_multiplier"] == baseline["atr_risk_multiplier"]
