# SVM-Guided Optimization Across All Strategies

Generated: 2026-09-09T17:11:07.952776+00:00

## Executive summary

Each strategy used its own baseline trades, SVM ranking, three-parameter maximum, walk-forward study, and untouched holdout. No live configuration was changed.

| Strategy | Selected parameters | SVM balanced accuracy | SVM ROC AUC | Walk-forward Sharpe | Holdout Sharpe | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Silver Bullet | `fvg_scale`, `stop_buffer_scale`, `min_risk_scale` | 0.500 | 0.333 | -0.129 → 1.105 | 2.869 → 2.259 | Retain current |
| Trendline | `candle_body_ratio_max`, `swing_lookback`, `candle_wick_ratio_min` | 0.621 | 0.514 | 2.213 → 2.370 | 2.281 → 2.347 | Exploratory only |
| Mutanabby | `risk_atr_length`, `supertrend_atr_length`, `atr_risk_multiplier` | 0.523 | 0.511 | -0.820 → 1.345 | 0.847 → -1.852 | Retain current |

## Method

- Final 240 calendar days; final 20% reserved before feature discovery.
- Linear-kernel, class-balanced SVM; first 70% of development trades fit the model and the remainder measure permutation importance.
- Features use information available by entry only. Positive validation permutation importance is mapped to an existing parameter; non-actionable context is ignored.
- At most 3 parameters per strategy enter Optuna; all others remain at current values.
- Optuna uses 4 chronological forward windows, 30 trials, seed 42, and a 0.25 fold-instability penalty.
- The untouched holdout is evaluated only after SVM ranking and Optuna selection.

## Silver Bullet

Development dates: 2025-11-25 to 2026-06-03. Untouched holdout: 2026-06-04 to 2026-07-22.

SVM samples: 18 fit / 9 validation.

| SVM metric | Result |
| --- | ---: |
| Accuracy | 0.444 |
| Majority accuracy | 0.667 |
| Balanced accuracy | 0.500 |
| ROC AUC | 0.333 |

### Parameter ranking

| Rank | Parameter | Score | Evidence | Selected |
| ---: | --- | ---: | --- | --- |
| 1 | `fvg_scale` | 0.102 | `fvg_size_to_range` | yes |
| 2 | `stop_buffer_scale` | 0.030 | `entry_gap_r`, `risk_to_range` | yes |
| 3 | `min_risk_scale` | 0.017 | `risk_to_range` | yes |
| 4 | `entry_in_fvg` | 0.013 | `entry_gap_r` | no |
| 5 | `swing_lookback` | 0.000 | `sweep_gap_to_range` | no |
| 6 | `sweep_lookback` | 0.000 | `bars_sweep_to_signal` | no |

Top ten baseline features by validation permutation importance:

| Feature | Importance | Std. dev. |
| --- | ---: | ---: |
| `close_location` | 0.147 | 0.109 |
| `fvg_size_to_range` | 0.102 | 0.118 |
| `return_6h` | 0.073 | 0.072 |
| `body_ratio` | 0.072 | 0.029 |
| `lower_wick_ratio` | 0.072 | 0.029 |
| `weekday` | 0.072 | 0.082 |
| `directional_return_6h` | 0.065 | 0.125 |
| `return_1h` | 0.063 | 0.036 |
| `symbol` | 0.035 | 0.041 |
| `window` | 0.035 | 0.041 |

### Backtest results

| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current / pooled walk-forward | -0.129 | 12 | $-36.81 | 0.95 | $377.45 | 66.7% |
| Guided / pooled walk-forward | 1.105 | 22 | $331.24 | 1.40 | $377.48 | 68.2% |
| Current / untouched holdout | 2.869 | 6 | $379.80 | 4.62 | $105.00 | 83.3% |
| Guided / untouched holdout | 2.259 | 10 | $342.32 | 2.53 | $210.00 | 70.0% |

| Fold | Current Sharpe | Guided Sharpe | Current trades | Guided trades |
| ---: | ---: | ---: | ---: | ---: |
| 1 | -1.482 | 1.454 | 3 | 9 |
| 2 | -3.433 | -0.418 | 2 | 5 |
| 3 | 4.691 | 5.587 | 3 | 4 |
| 4 | -2.840 | -2.840 | 4 | 4 |

Untouched holdout by symbol:

| Symbol | Current Sharpe | Guided Sharpe | Current trades | Guided trades | Current net | Guided net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| XAUUSDm | 2.730 | -1.517 | 1 | 3 | $36.29 | $-62.35 |
| USTECm | 2.602 | 3.010 | 5 | 7 | $343.51 | $404.67 |

Selected full configuration:

```json
{
  "breakeven_r": 0.25,
  "early_exit_r": 0.4,
  "entry_in_fvg": "mid",
  "fvg_scale": 0.6007252074699736,
  "min_risk_scale": 0.9826234866077894,
  "stop_buffer_scale": 0.9971587739256565,
  "sweep_lookback": 10,
  "swing_lookback": 3,
  "target_mode": "opposite_liquidity",
  "trail_r": 0.1
}
```

## Trendline

Development dates: 2025-11-25 to 2026-06-03. Untouched holdout: 2026-06-04 to 2026-07-22.

SVM samples: 53 fit / 24 validation.

| SVM metric | Result |
| --- | ---: |
| Accuracy | 0.625 |
| Majority accuracy | 0.583 |
| Balanced accuracy | 0.621 |
| ROC AUC | 0.514 |

### Parameter ranking

| Rank | Parameter | Score | Evidence | Selected |
| ---: | --- | ---: | --- | --- |
| 1 | `candle_body_ratio_max` | 0.231 | `body_ratio`, `directional_candle_body`, `close_location` | yes |
| 2 | `swing_lookback` | 0.148 | `line_anchor_span`, `line_age` | yes |
| 3 | `candle_wick_ratio_min` | 0.118 | `upper_wick_ratio`, `lower_wick_ratio` | yes |
| 4 | `stop_buffer_scale` | 0.083 | `entry_gap_r`, `risk_to_range` | no |
| 5 | `steepness_max_ratio` | 0.078 | `directional_line_slope` | no |
| 6 | `touch_scale` | 0.030 | `touch_gap_to_range` | no |
| 7 | `min_risk_scale` | 0.025 | `risk_to_range` | no |

Top ten baseline features by validation permutation importance:

| Feature | Importance | Std. dev. |
| --- | ---: | ---: |
| `hour_cos` | 0.172 | 0.076 |
| `line_anchor_span` | 0.126 | 0.044 |
| `return_6h` | 0.125 | 0.060 |
| `body_ratio` | 0.116 | 0.060 |
| `lower_wick_ratio` | 0.104 | 0.051 |
| `price_vs_sma20_range` | 0.087 | 0.055 |
| `hour_sin` | 0.079 | 0.050 |
| `directional_candle_body` | 0.079 | 0.043 |
| `directional_line_slope` | 0.078 | 0.040 |
| `symbol` | 0.061 | 0.066 |

### Backtest results

| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current / pooled walk-forward | 2.213 | 31 | $1,725.03 | 2.15 | $506.72 | 54.8% |
| Guided / pooled walk-forward | 2.370 | 32 | $1,858.52 | 2.24 | $506.72 | 56.2% |
| Current / untouched holdout | 2.281 | 19 | $675.21 | 1.85 | $449.40 | 42.1% |
| Guided / untouched holdout | 2.347 | 20 | $702.62 | 1.89 | $449.40 | 45.0% |

| Fold | Current Sharpe | Guided Sharpe | Current trades | Guided trades |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1.152 | 1.152 | 3 | 3 |
| 2 | 0.113 | 0.113 | 7 | 7 |
| 3 | 5.273 | 5.651 | 10 | 11 |
| 4 | -2.189 | -2.189 | 11 | 11 |

Untouched holdout by symbol:

| Symbol | Current Sharpe | Guided Sharpe | Current trades | Guided trades | Current net | Guided net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DE30m | 2.201 | 2.265 | 7 | 8 | $256.32 | $283.73 |
| USDJPYm | 1.687 | 1.687 | 9 | 9 | $450.17 | $450.17 |
| USTECm | -0.699 | -0.699 | 3 | 3 | $-31.28 | $-31.28 |

Selected full configuration:

```json
{
  "breakeven_r": 1.0,
  "candle_body_ratio_max": 0.29200440182653065,
  "candle_wick_ratio_min": 1.6284810075923466,
  "min_risk_scale": 1.0,
  "obstruction_scale": 1.0,
  "steepness_max_ratio": 1.0,
  "stop_buffer_scale": 1.0,
  "swing_lookback": 3,
  "touch_scale": 1.0,
  "trail_r": 0.5
}
```

## Mutanabby

Development dates: 2025-11-25 to 2026-06-04. Untouched holdout: 2026-06-05 to 2026-07-22.

SVM samples: 58 fit / 26 validation.

| SVM metric | Result |
| --- | ---: |
| Accuracy | 0.500 |
| Majority accuracy | 0.731 |
| Balanced accuracy | 0.523 |
| ROC AUC | 0.511 |

### Parameter ranking

| Rank | Parameter | Score | Evidence | Selected |
| ---: | --- | ---: | --- | --- |
| 1 | `risk_atr_length` | 0.005 | `atr_to_range`, `risk_to_range` | yes |
| 2 | `supertrend_atr_length` | 0.005 | `supertrend_gap_to_range`, `atr_to_range` | yes |
| 3 | `atr_risk_multiplier` | 0.002 | `risk_to_range` | yes |
| 4 | `sensitivity` | 0.002 | `supertrend_gap_to_range`, `return_volatility_24h` | no |
| 5 | `trend_sma_length` | 0.000 | `trend_sma_gap_to_range`, `price_vs_sma20_range` | no |

Top ten baseline features by validation permutation importance:

| Feature | Importance | Std. dev. |
| --- | ---: | ---: |
| `direction` | 0.006 | 0.018 |
| `candle_range_vs_24h` | 0.004 | 0.009 |
| `atr_to_range` | 0.003 | 0.015 |
| `risk_to_range` | 0.002 | 0.007 |
| `supertrend_gap_to_range` | 0.002 | 0.036 |
| `hour_sin` | 0.002 | 0.082 |
| `directional_return_6h` | 0.002 | 0.006 |
| `close_location` | 0.001 | 0.020 |
| `return_24h` | 0.001 | 0.020 |
| `lower_wick_ratio` | 0.000 | 0.000 |

### Backtest results

| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current / pooled walk-forward | -0.820 | 46 | $-526.15 | 0.84 | $1,508.74 | 28.3% |
| Guided / pooled walk-forward | 1.345 | 44 | $897.40 | 1.32 | $1,118.91 | 36.4% |
| Current / untouched holdout | 0.847 | 15 | $254.62 | 1.24 | $420.00 | 33.3% |
| Guided / untouched holdout | -1.852 | 16 | $-401.09 | 0.67 | $697.46 | 25.0% |

| Fold | Current Sharpe | Guided Sharpe | Current trades | Guided trades |
| ---: | ---: | ---: | ---: | ---: |
| 1 | -5.030 | -4.636 | 13 | 12 |
| 2 | -0.660 | 0.903 | 16 | 17 |
| 3 | 2.510 | 5.676 | 5 | 3 |
| 4 | -0.208 | 3.443 | 12 | 12 |

Untouched holdout by symbol:

| Symbol | Current Sharpe | Guided Sharpe | Current trades | Guided trades | Current net | Guided net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| US30m | 3.951 | 3.233 | 2 | 3 | $676.89 | $571.33 |
| JP225m | -4.902 | -6.455 | 3 | 5 | $-315.00 | $-496.75 |
| USDJPYm | -0.846 | -5.736 | 4 | 4 | $-89.74 | $-420.00 |
| ETHUSDm | -0.119 | -0.822 | 6 | 4 | $-17.52 | $-55.66 |

Selected full configuration:

```json
{
  "atr_risk_multiplier": 1.1,
  "breakeven_r": 0.0,
  "exit_on_opposite_signal": false,
  "risk_atr_length": 12,
  "sensitivity": 6.0,
  "split_targets": true,
  "supertrend_atr_length": 17,
  "tp1_fraction": 0.5,
  "tp1_rr": 3.0,
  "tp2_gap": 1.0,
  "trend_sma_length": 13
}
```

## Limitations

SVM importance is associative, parameter mappings are hypotheses, and the number of baseline trades can be small. A favorable holdout can also be caused by one or two trades. Treat the holdout and per-symbol consistency as decisive, and forward-test any candidate before changing live settings.

Runtime: 133.1 seconds.

Reproduce from `backend/`:

```powershell
python backtests/all_strategies_svm_guided_optuna.py --trials 30 --max-parameters 3 --lookback-days 240 --seed 42
```
