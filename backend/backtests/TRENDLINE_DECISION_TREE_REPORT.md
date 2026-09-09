# Trendline Win/Loss Decision Tree

Generated: 2026-09-09T14:22:43.234924+00:00

## Conclusion

The tree does not generalize well enough to use as a live trade filter. Treat its splits as exploratory hypotheses only.

## Experimental design

- Portfolio: DE30m, USDJPYm, USTECm using the current live Trendline configuration.
- Data: final 240 common calendar days; chronological cutoff `2026-05-12`.
- Samples: 66 training trades (56.1% winners), 30 holdout trades (43.3% winners).
- Model: class-balanced decision tree, max depth `8`, minimum `8` training trades per leaf, seed `42`.
- Every feature is available at signal close or next-bar fill. P/L, exit reason, exit time, future bars, and test labels are excluded from training features.
- Training time-series cross-validation is diagnostic only; tree settings were fixed in advance and were not tuned against the holdout.

## Holdout classification

| Metric | Result |
| --- | ---: |
| Accuracy | 0.400 |
| Majority-class accuracy | 0.567 |
| Balanced accuracy | 0.389 |
| ROC AUC | 0.432 |
| Winner precision | 0.308 |
| Winner recall | 0.308 |
| Winner F1 | 0.308 |
| Training time-series CV balanced accuracy | 0.530 ± 0.037 |

Confusion matrix (actual rows, predicted columns):

|  | Predicted loss | Predicted win |
| --- | ---: | ---: |
| Actual loss | 8 | 9 |
| Actual win | 9 | 4 |

## Hypothetical holdout filter

A fixed predicted-win threshold of `0.60` is shown for diagnosis; it was not selected on the test set.

| Holdout trades | Trades | Win rate | Net P/L | Profit factor | Daily P/L Sharpe |
| --- | ---: | ---: | ---: | ---: | ---: |
| All current Trendline trades | 30 | 43.3% | $482.21 | 1.33 | 1.233 |
| Tree probability ≥ 0.60 | 13 | 30.8% | $-174.44 | 0.75 | -0.947 |

## Learned decision rules

The leaf values are class-weighted counts because the model balances winners and losers.

```text
|--- directional_candle_body <= 0.379
|   |--- line_anchor_span <= 8.500
|   |   |--- class: 1
|   |--- line_anchor_span >  8.500
|   |   |--- directional_candle_body <= 0.039
|   |   |   |--- class: 1
|   |   |--- directional_candle_body >  0.039
|   |   |   |--- class: 0
|--- directional_candle_body >  0.379
|   |--- directional_line_slope <= 0.066
|   |   |--- directional_return_6h <= -0.000
|   |   |   |--- class: 0
|   |   |--- directional_return_6h >  -0.000
|   |   |   |--- class: 1
|   |--- directional_line_slope >  0.066
|   |   |--- class: 0
```

## Feature evidence

### Features used by the fitted tree

| Feature | Tree importance | Training winner median | Training loser median |
| --- | ---: | ---: | ---: |
| `directional_candle_body` | 0.530 | 0.151 | 0.478 |
| `line_anchor_span` | 0.243 | 8.000 | 10.000 |
| `directional_return_6h` | 0.123 | -0.000 | 0.000 |
| `directional_line_slope` | 0.103 | 0.016 | 0.087 |

### Holdout permutation importance

Positive values mean shuffling the feature reduced holdout balanced accuracy. With this small holdout, these estimates are noisy.

| Feature | Mean importance | Std. dev. |
| --- | ---: | ---: |
| `directional_return_6h` | 0.010 | 0.033 |
| `directional_line_slope` | 0.007 | 0.042 |
| `symbol` | 0.000 | 0.000 |
| `direction` | 0.000 | 0.000 |
| `risk_to_range` | 0.000 | 0.000 |
| `entry_gap_r` | 0.000 | 0.000 |
| `planned_reward_r` | 0.000 | 0.000 |
| `candle_range_vs_24h` | 0.000 | 0.000 |
| `body_ratio` | 0.000 | 0.000 |
| `upper_wick_ratio` | 0.000 | 0.000 |

## Feature definitions

- `risk_to_range`: initial stop distance divided by the prior 24-hour average candle range.
- `entry_gap_r`: next-bar fill movement away from the signal close, measured in initial R.
- `directional_*`: positive means aligned with the trade direction; negative means opposed.
- `line_anchor_span` / `line_age`: hours between anchors and from the newest anchor to the touch.
- `touch_gap_to_range`: distance between the touched candle extreme and extrapolated trendline, normalized by recent range.
- Returns, volatility, SMA distance, candle geometry, hour, weekday, symbol, and direction use only information known at entry.

## Limitations

This is association, not causation. The sample is small, the same broker-history cost model is reused, and the backtester tracks one open Trendline trade at a time even though the live configuration permits concurrent positions. A decision tree can find unstable thresholds easily; no live filter should be added without more trades, repeated walk-forward validation, and demo forward-testing.

Runtime: 220.6 seconds.

Reproduce from `backend/`:

```powershell
python backtests/trendline_decision_tree.py --lookback-days 240 --train-fraction 0.7 --seed 42
```
