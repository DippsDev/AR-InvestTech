# Trendline Walk-Forward Optimization Report

Generated: 2026-09-09T14:59:41.801880+00:00
Git commit: `76563f5`

## Executive summary

Optuna walk-forward Sharpe: 2.213 → 3.389. Untouched holdout Sharpe: 2.281 → 0.551.

Retain the current parameters; the selected candidate did not improve the untouched holdout.

## Method

- Portfolio: DE30m, USDJPYm, USTECm.
- Data: final 240 calendar days available in the repository.
- Development/holdout split: 80%/20%; the holdout was evaluated only after selection.
- Walk-forward structure: 4 expanding chronological folds; the first 50% of development history initializes the first fold.
- Objective: pooled annualized daily-P/L Sharpe across forward windows minus 0.25 × the standard deviation of fold Sharpes.
- Sparse-trial guard: at least 3 trades in every forward window.
- Optimizer: Optuna TPE, 40 trials, seed 42; the current configuration is always trial 0.
- Warmup: up to 300 bars before each scored window. Only entries inside that window count.
- Costs: $5 round-trip commission; spread and slippage scale with each symbol's median M5 range; fixed $100 risk per trade.
- Search scope: line geometry, touch/obstruction tolerance, stop/risk filters, candlestick confirmation, and breakeven/trailing. Split targets remain at the current 3R/4R settings to keep the search space controlled.

## Partitions

Development: 2025-11-25 to 2026-06-03 (164 dates).  
Untouched holdout: 2026-06-04 to 2026-07-22 (42 dates).

| Fold | Expanding history | Forward validation | Train dates | Validation dates |
| ---: | --- | --- | ---: | ---: |
| 1 | 2025-11-25 to 2026-02-27 | 2026-03-01 to 2026-03-24 | 82 | 21 |
| 2 | 2025-11-25 to 2026-03-24 | 2026-03-25 to 2026-04-17 | 103 | 21 |
| 3 | 2025-11-25 to 2026-04-17 | 2026-04-19 to 2026-05-11 | 124 | 20 |
| 4 | 2025-11-25 to 2026-05-11 | 2026-05-12 to 2026-06-03 | 144 | 20 |

## Aggregate results

| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current / pooled walk-forward | 2.213 | 31 | $1,725.03 | 2.15 | $506.72 | 54.8% |
| Optuna / pooled walk-forward | 3.389 | 24 | $1,798.71 | 2.21 | $494.65 | 41.7% |
| Current / untouched holdout | 2.281 | 19 | $675.21 | 1.85 | $449.40 | 42.1% |
| Optuna / untouched holdout | 0.551 | 18 | $158.45 | 1.11 | $630.00 | 27.8% |

## Fold results

| Fold | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.152 | 4.580 | 3 | 3 | $117.41 | $563.06 |
| 2 | 0.113 | 2.298 | 7 | 8 | $12.57 | $375.18 |
| 3 | 5.273 | -0.331 | 10 | 5 | $1,788.04 | $-23.34 |
| 4 | -2.189 | 5.661 | 11 | 8 | $-193.00 | $883.82 |

## Holdout by symbol

| Symbol | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DE30m | 2.201 | 3.437 | 7 | 6 | $256.32 | $683.59 |
| USDJPYm | 1.687 | -1.539 | 9 | 10 | $450.17 | $-315.14 |
| USTECm | -0.699 | -3.909 | 3 | 2 | $-31.28 | $-210.00 |

## Selected parameters

```json
{
  "breakeven_r": 0.0,
  "candle_body_ratio_max": 0.39630688853990315,
  "candle_wick_ratio_min": 1.9228423153353926,
  "min_risk_scale": 1.4270757173014972,
  "obstruction_scale": 0.8005666961158854,
  "steepness_max_ratio": 1.25,
  "stop_buffer_scale": 1.3546510296331469,
  "swing_lookback": 4,
  "touch_scale": 0.9931393675756556,
  "trail_r": 0.0
}
```

## Top trials

| Rank | Trial | Objective | Pooled Sharpe | Fold Sharpes | Fold trades | Net P/L |
| ---: | ---: | ---: | ---: | --- | --- | ---: |
| 1 | 32 | 2.814 | 3.389 | `[4.579766, 2.29763, -0.33131, 5.661062]` | `[3, 8, 5, 8]` | $1,798.71 |
| 2 | 18 | 2.628 | 2.996 | `[4.579389, 2.229215, 0.864242, 4.030565]` | `[3, 8, 4, 7]` | $1,561.39 |
| 3 | 21 | 2.619 | 3.074 | `[1.18885, 2.373962, 5.885635, 1.841417]` | `[3, 6, 7, 9]` | $1,699.78 |
| 4 | 17 | 2.580 | 2.955 | `[1.188937, 2.758509, 5.150365, 1.84863]` | `[3, 6, 8, 9]` | $1,596.68 |
| 5 | 33 | 2.532 | 3.127 | `[4.579637, 1.560818, -0.333604, 5.654118]` | `[3, 9, 5, 8]` | $1,688.75 |
| 6 | 24 | 2.424 | 2.904 | `[4.57978, 2.300106, -0.33106, 4.053925]` | `[3, 8, 5, 7]` | $1,471.31 |
| 7 | 31 | 2.420 | 2.899 | `[4.579722, 2.289741, -0.332101, 4.050424]` | `[3, 8, 5, 7]` | $1,469.11 |
| 8 | 23 | 2.385 | 2.821 | `[1.188726, 1.779332, 5.583488, 1.830993]` | `[3, 7, 8, 9]` | $1,487.03 |
| 9 | 12 | 2.371 | 2.808 | `[1.188448, 1.752104, 5.582986, 1.807573]` | `[3, 7, 8, 9]` | $1,480.85 |
| 10 | 14 | 2.360 | 2.771 | `[1.189584, 2.827054, 5.151553, 1.098436]` | `[3, 6, 8, 10]` | $1,505.63 |

## Interpretation

The walk-forward windows reduce dependence on one lucky train/test cutoff, while the final holdout remains the clean generalization check. Optuna still compares many alternatives, and the sample can remain small, so a favorable result is a candidate for demo forward-testing—not permission to promote it automatically.

Total runtime: 29.4 seconds.

Reproduce from `backend/`:

```powershell
python backtests/trendline_walk_forward.py --trials 40 --folds 4 --lookback-days 240 --seed 42
```
