# SVM-Guided Trendline Optimization Report

Generated: 2026-09-09T15:57:28.609315+00:00

## Conclusion

Do not promote automatically. The candidate improved the holdout, but the SVM's own validation discrimination was weak.

The SVM selected only **3 parameters**: `candle_body_ratio_max`, `swing_lookback`, `candle_wick_ratio_min`.

Walk-forward Sharpe: 2.213 → 2.370. Untouched holdout Sharpe: 2.281 → 2.347.

## Experimental design

- Stage 1: fit a class-balanced linear-kernel SVM to wins/losses from the baseline Trendline strategy.
- SVM samples: 53 early-development trades for fitting and 24 later-development trades for permutation importance.
- Inputs contain only information available by entry. Exit outcome is the label; future-market features are excluded.
- Only positive permutation importance from the later SVM validation slice counts. Non-actionable context such as symbol, hour, and returns is reported but cannot select a strategy parameter.
- Stage 2: optimize at most 3 mapped parameters over 4 chronological forward windows using 40 Optuna trials.
- Final holdout starts `2026-06-04` and is untouched by SVM fitting, feature ranking, and Optuna selection.
- Objective: pooled daily-P/L Sharpe minus 0.25 × fold-Sharpe standard deviation; every fold requires at least 3 trades.
- All unselected parameters remain exactly at the current baseline values.

## SVM validation

| Metric | Result |
| --- | ---: |
| Accuracy | 0.625 |
| Majority-class accuracy | 0.583 |
| Balanced accuracy | 0.621 |
| ROC AUC | 0.514 |

A model below roughly 0.55 balanced accuracy or ROC AUC has weak evidence for generalizable feature ranking; parameter selection should then be treated as exploratory.

## Baseline feature importance

Positive values mean that shuffling the feature reduced validation balanced accuracy.

| Feature | Permutation importance | Std. dev. | Actionable mapping |
| --- | ---: | ---: | --- |
| `hour_cos` | 0.160 | 0.071 | — |
| `line_anchor_span` | 0.135 | 0.050 | `swing_lookback` |
| `return_6h` | 0.132 | 0.057 | — |
| `body_ratio` | 0.117 | 0.043 | `candle_body_ratio_max` |
| `price_vs_sma20_range` | 0.109 | 0.051 | — |
| `lower_wick_ratio` | 0.108 | 0.048 | `candle_wick_ratio_min` |
| `directional_line_slope` | 0.099 | 0.047 | `steepness_max_ratio` |
| `hour_sin` | 0.082 | 0.053 | — |
| `symbol` | 0.067 | 0.060 | — |
| `planned_reward_r` | 0.067 | 0.050 | — |
| `return_3h` | 0.064 | 0.037 | — |
| `directional_candle_body` | 0.059 | 0.038 | `candle_body_ratio_max` |
| `return_volatility_24h` | 0.058 | 0.036 | — |
| `entry_gap_r` | 0.056 | 0.042 | `stop_buffer_scale` |
| `weekday` | 0.052 | 0.035 | — |
| `return_24h` | 0.051 | 0.061 | — |
| `candle_range_vs_24h` | 0.039 | 0.066 | — |
| `directional_return_6h` | 0.038 | 0.031 | — |
| `close_location` | 0.035 | 0.025 | `candle_body_ratio_max` |
| `risk_to_range` | 0.027 | 0.015 | `stop_buffer_scale`, `min_risk_scale` |
| `touch_gap_to_range` | 0.026 | 0.028 | `touch_scale` |
| `direction` | 0.024 | 0.024 | — |
| `line_age` | 0.022 | 0.027 | `swing_lookback` |
| `upper_wick_ratio` | 0.021 | 0.018 | `candle_wick_ratio_min` |
| `return_1h` | 0.000 | 0.000 | — |

## Parameter ranking

A parameter score is the sum of positive validation permutation importance for its mapped baseline-trade features.

| Rank | Parameter | Score | Evidence features | Selected |
| ---: | --- | ---: | --- | --- |
| 1 | `candle_body_ratio_max` | 0.211 | `body_ratio`, `directional_candle_body`, `close_location` | yes |
| 2 | `swing_lookback` | 0.157 | `line_anchor_span`, `line_age` | yes |
| 3 | `candle_wick_ratio_min` | 0.129 | `upper_wick_ratio`, `lower_wick_ratio` | yes |
| 4 | `steepness_max_ratio` | 0.099 | `directional_line_slope` | no |
| 5 | `stop_buffer_scale` | 0.083 | `entry_gap_r`, `risk_to_range` | no |
| 6 | `min_risk_scale` | 0.027 | `risk_to_range` | no |
| 7 | `touch_scale` | 0.026 | `touch_gap_to_range` | no |

## Optimization results

| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current / pooled walk-forward | 2.213 | 31 | $1,725.03 | 2.15 | $506.72 | 54.8% |
| SVM-guided Optuna / pooled walk-forward | 2.370 | 32 | $1,858.52 | 2.24 | $506.72 | 56.2% |
| Current / untouched holdout | 2.281 | 19 | $675.21 | 1.85 | $449.40 | 42.1% |
| SVM-guided Optuna / untouched holdout | 2.347 | 20 | $702.62 | 1.89 | $449.40 | 45.0% |

### Forward folds

| Fold | Current Sharpe | Guided Sharpe | Current trades | Guided trades |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.152 | 1.152 | 3 | 3 |
| 2 | 0.113 | 0.113 | 7 | 7 |
| 3 | 5.273 | 5.651 | 10 | 11 |
| 4 | -2.189 | -2.189 | 11 | 11 |

### Untouched holdout by symbol

| Symbol | Current Sharpe | Guided Sharpe | Current trades | Guided trades | Current net | Guided net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DE30m | 2.201 | 2.265 | 7 | 8 | $256.32 | $283.73 |
| USDJPYm | 1.687 | 1.687 | 9 | 9 | $450.17 | $450.17 |
| USTECm | -0.699 | -0.699 | 3 | 3 | $-31.28 | $-31.28 |

## Selected configuration

```json
{
  "breakeven_r": 1.0,
  "candle_body_ratio_max": 0.29456466900677575,
  "candle_wick_ratio_min": 1.5501330363049814,
  "min_risk_scale": 1.0,
  "obstruction_scale": 1.0,
  "steepness_max_ratio": 1.0,
  "stop_buffer_scale": 1.0,
  "swing_lookback": 3,
  "touch_scale": 1.0,
  "trail_r": 0.5
}
```

Only the selected keys above differ from—or were eligible to differ from—the baseline.

## Top trials

| Rank | Trial | Objective | Pooled Sharpe | Fold Sharpes | Fold trades | Parameters |
| ---: | ---: | ---: | ---: | --- | --- | --- |
| 1 | 14 | 1.657 | 2.370 | `[1.151697, 0.113179, 5.650941, -2.189218]` | `[3, 7, 11, 11]` | `{"candle_body_ratio_max": 0.29456466900677575, "candle_wick_ratio_min": 1.5501330363049814, "swing_lookback": 3}` |
| 2 | 34 | 1.657 | 2.370 | `[1.151697, 0.113179, 5.650941, -2.189218]` | `[3, 7, 11, 11]` | `{"candle_body_ratio_max": 0.3809222903629507, "candle_wick_ratio_min": 1.71272944348241, "swing_lookback": 3}` |
| 3 | 22 | 1.543 | 2.273 | `[1.151697, -0.529818, 5.650941, -2.189218]` | `[3, 8, 11, 11]` | `{"candle_body_ratio_max": 0.353351303419518, "candle_wick_ratio_min": 1.6080175688284566, "swing_lookback": 3}` |
| 4 | 23 | 1.543 | 2.273 | `[1.151697, -0.529818, 5.650941, -2.189218]` | `[3, 8, 11, 11]` | `{"candle_body_ratio_max": 0.3997391788730809, "candle_wick_ratio_min": 1.6121298149797685, "swing_lookback": 3}` |
| 5 | 25 | 1.543 | 2.273 | `[1.151697, -0.529818, 5.650941, -2.189218]` | `[3, 8, 11, 11]` | `{"candle_body_ratio_max": 0.37645034594808113, "candle_wick_ratio_min": 1.6078193456683647, "swing_lookback": 3}` |
| 6 | 27 | 1.543 | 2.273 | `[1.151697, -0.529818, 5.650941, -2.189218]` | `[3, 8, 11, 11]` | `{"candle_body_ratio_max": 0.3763486542418817, "candle_wick_ratio_min": 1.676393796402361, "swing_lookback": 3}` |
| 7 | 31 | 1.543 | 2.273 | `[1.151697, -0.529818, 5.650941, -2.189218]` | `[3, 8, 11, 11]` | `{"candle_body_ratio_max": 0.384226979583364, "candle_wick_ratio_min": 1.590706332981681, "swing_lookback": 3}` |
| 8 | 32 | 1.543 | 2.273 | `[1.151697, -0.529818, 5.650941, -2.189218]` | `[3, 8, 11, 11]` | `{"candle_body_ratio_max": 0.36788831383643783, "candle_wick_ratio_min": 1.6737722214203985, "swing_lookback": 3}` |
| 9 | 33 | 1.543 | 2.273 | `[1.151697, -0.529818, 5.650941, -2.189218]` | `[3, 8, 11, 11]` | `{"candle_body_ratio_max": 0.39983847393190836, "candle_wick_ratio_min": 1.5835441706159517, "swing_lookback": 3}` |
| 10 | 0 | 1.537 | 2.213 | `[1.151697, 0.113179, 5.272906, -2.189218]` | `[3, 7, 10, 11]` | `{"candle_body_ratio_max": 0.3, "candle_wick_ratio_min": 2.0, "swing_lookback": 3}` |

## Limitations

SVM importance is association, not a causal estimate of changing a parameter. The baseline sample is small, mapped features can be correlated, and Optuna still compares multiple alternatives. The final holdout therefore remains decisive; no candidate should be promoted from SVM importance alone.

Runtime: 36.9 seconds.

Reproduce from `backend/`:

```powershell
python backtests/trendline_svm_guided_optuna.py --trials 40 --max-parameters 3 --lookback-days 240 --seed 42
```
