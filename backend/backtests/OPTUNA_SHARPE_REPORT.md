# Optuna Sharpe Optimization Report

Generated: 2026-09-08T22:36:32.303205+00:00
Git commit: `76563f5`

## Executive summary

- **Silver Bullet:** test Sharpe 0.609 → 1.313. Improved on both train and holdout; this is positive single-holdout evidence.
- **Trendline:** test Sharpe 1.233 → -1.409. Train improved but holdout did not; treat this configuration as overfit.
- **Mutanabby:** test Sharpe -0.010 → -2.736. Train improved but holdout did not; treat this configuration as overfit.

## Recommendation

- **Silver Bullet:** Do not promote automatically. Forward-test the candidate and run multiple walk-forward folds; the holdout contains only 10 trades. The gain came from USTECm, while XAUUSDm deteriorated.
- **Trendline:** Retain the current parameters; the Optuna winner failed the holdout.
- **Mutanabby:** Retain the current parameters; the Optuna winner failed the holdout.

## Method

- Objective: maximize annualized daily-P/L Sharpe on the training set only.
- Split: first 70% of available dates for training, final 30% for the untouched holdout.
- Optimizer: Optuna TPE, seed `42`. Trial budgets: Silver Bullet `20`, Trendline `8`, Mutanabby `20`.
- History window: the final `240` calendar days available to each portfolio.
- Guardrail: trials with fewer than `15` aggregate training trades receive an invalid score.
- Trendline runtime guard: swing lookback, steepness, and obstruction geometry stay at current values; the study tunes touch sensitivity, risk filters, candle confirmation, targets, and trade management.
- Test initialization: `300` pre-cutoff bars initialize indicators; only post-cutoff entries are scored.
- Sharpe: mean daily fixed-risk P/L divided by sample daily-P/L volatility, annualized from the observed trading-date frequency. No-trade dates present in the source data count as zero; risk-free rate is zero.
- Costs: the repository's standard $5 round-trip commission, with spread and slippage scaled from each instrument's median M5 range. Risk is fixed at $100 per trade.
- Current benchmark: the configurations actually constructed by `bot.py`, including per-symbol overrides from `multi_symbol_targets.py`.

## Data partitions

| Strategy | Symbols | Cutoff (test starts) | Train dates | Test dates |
| --- | --- | --- | ---: | ---: |
| Silver Bullet | XAUUSDm, USTECm | 2026-05-12 | 144 | 62 |
| Trendline | DE30m, USDJPYm, USTECm | 2026-05-12 | 144 | 62 |
| Mutanabby | US30m, JP225m, USDJPYm, ETHUSDm | 2026-05-12 | 168 | 72 |

## Aggregate results

| Strategy | Configuration | Partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Silver Bullet | Current | Train | 0.873 | 23 | $355.52 | 1.40 | $383.50 | 56.5% |
| Silver Bullet | Current | Test | 0.609 | 10 | $135.07 | 1.27 | $377.45 | 70.0% |
| Silver Bullet | Optuna | Train | 2.023 | 40 | $1,008.21 | 2.29 | $448.91 | 65.0% |
| Silver Bullet | Optuna | Test | 1.313 | 10 | $179.54 | 1.68 | $112.12 | 50.0% |
| Trendline | Current | Train | 1.826 | 66 | $2,199.99 | 1.70 | $604.66 | 56.1% |
| Trendline | Current | Test | 1.233 | 30 | $482.21 | 1.33 | $449.40 | 43.3% |
| Trendline | Optuna | Train | 3.513 | 57 | $4,283.70 | 2.79 | $316.92 | 61.4% |
| Trendline | Optuna | Test | -1.409 | 21 | $-323.07 | 0.73 | $441.51 | 42.9% |
| Mutanabby | Current | Train | 0.991 | 76 | $1,226.26 | 1.23 | $1,586.47 | 32.9% |
| Mutanabby | Current | Test | -0.010 | 27 | $15.44 | 1.01 | $749.95 | 29.6% |
| Mutanabby | Optuna | Train | 2.002 | 87 | $2,766.39 | 1.45 | $990.64 | 31.0% |
| Mutanabby | Optuna | Test | -2.736 | 32 | $-970.53 | 0.62 | $1,255.77 | 21.9% |

## Holdout results by symbol

### Silver Bullet

| Symbol | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| XAUUSDm | 3.094 | -0.020 | 2 | 4 | $56.98 | $-1.16 |
| USTECm | 0.353 | 1.459 | 8 | 6 | $78.09 | $180.71 |

### Trendline

| Symbol | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DE30m | 0.793 | -0.538 | 11 | 5 | $126.57 | $-49.08 |
| USDJPYm | 1.333 | -2.840 | 10 | 7 | $430.55 | $-297.09 |
| USTECm | -0.460 | 0.127 | 9 | 9 | $-74.91 | $23.11 |

### Mutanabby

| Symbol | Current Sharpe | Optuna Sharpe | Current trades | Optuna trades | Current net | Optuna net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| US30m | 1.585 | 0.638 | 5 | 5 | $361.89 | $139.15 |
| JP225m | -5.673 | -1.258 | 9 | 10 | $-749.95 | $-299.48 |
| USDJPYm | -0.693 | -1.031 | 4 | 4 | $-89.74 | $-122.10 |
| ETHUSDm | 1.708 | -2.829 | 9 | 13 | $493.24 | $-688.10 |

## Selected parameters

### Silver Bullet

```json
{
  "breakeven_r": 0.25,
  "early_exit_r": 0.4,
  "entry_in_fvg": "near_edge",
  "fvg_scale": 0.7768954600866237,
  "min_risk_scale": 0.9016235565290456,
  "stop_buffer_scale": 1.652856869139759,
  "sweep_lookback": 10,
  "swing_lookback": 4,
  "target_mode": "opposite_liquidity",
  "trail_r": 0.1
}
```

Top five training trials:

| Rank | Trial | Train Sharpe | Trades | Net P/L | Parameters |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 15 | 2.023 | 40 | $1,008.21 | `{"breakeven_r": 0.25, "early_exit_r": 0.4, "entry_in_fvg": "near_edge", "fvg_scale": 0.7768954600866237, "min_risk_scale": 0.9016235565290456, "stop_buffer_scale": 1.652856869139759, "sweep_lookback": 10, "swing_lookback": 4, "target_mode": "opposite_liquidity", "trail_r": 0.1}` |
| 2 | 4 | 0.954 | 70 | $1,012.67 | `{"breakeven_r": 0.5, "early_exit_r": 0.25, "entry_in_fvg": "near_edge", "fvg_scale": 0.7004694411911279, "min_risk_scale": 0.5489472670158395, "rr": 1.0, "stop_buffer_scale": 1.5203399639856587, "sweep_lookback": 16, "swing_lookback": 3, "target_mode": "rr", "trail_r": 0.5}` |
| 3 | 0 | 0.873 | 23 | $355.52 | `{"breakeven_r": 0.25, "early_exit_r": 0.4, "entry_in_fvg": "mid", "fvg_scale": 1.0, "min_risk_scale": 1.0, "stop_buffer_scale": 1.0, "sweep_lookback": 10, "swing_lookback": 3, "target_mode": "opposite_liquidity", "trail_r": 0.1}` |
| 4 | 9 | 0.523 | 21 | $248.37 | `{"breakeven_r": 0.5, "early_exit_r": 0.0, "entry_in_fvg": "near_edge", "fvg_scale": 0.7559926200410922, "min_risk_scale": 0.7926988245865997, "rr": 2.75, "stop_buffer_scale": 0.7452614800881509, "sweep_lookback": 6, "swing_lookback": 4, "target_mode": "rr", "trail_r": 0.5}` |
| 5 | 11 | 0.451 | 25 | $161.98 | `{"breakeven_r": 0.25, "early_exit_r": 0.4, "entry_in_fvg": "mid", "fvg_scale": 0.9212540434446155, "min_risk_scale": 1.1302203085848241, "stop_buffer_scale": 0.9346389697437122, "sweep_lookback": 10, "swing_lookback": 3, "target_mode": "opposite_liquidity", "trail_r": 0.1}` |

### Trendline

```json
{
  "breakeven_r": 1.0,
  "candle_body_ratio_max": 0.384233796745903,
  "candle_wick_ratio_min": 1.0722357374328908,
  "min_risk_scale": 1.672087289670422,
  "obstruction_scale": 1.0,
  "split_targets": true,
  "steepness_max_ratio": 1.0,
  "stop_buffer_scale": 0.503841722600918,
  "swing_lookback": 3,
  "touch_scale": 0.7830337714867598,
  "tp1_fraction": 0.25,
  "tp1_rr": 1.5,
  "tp2_gap": 2.5,
  "trail_r": 0.5
}
```

Top five training trials:

| Rank | Trial | Train Sharpe | Trades | Net P/L | Parameters |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 4 | 3.513 | 57 | $4,283.70 | `{"breakeven_r": 1.0, "candle_body_ratio_max": 0.384233796745903, "candle_wick_ratio_min": 1.0722357374328908, "min_risk_scale": 1.672087289670422, "split_targets": true, "stop_buffer_scale": 0.503841722600918, "touch_scale": 0.7830337714867598, "tp1_fraction": 0.25, "tp1_rr": 1.5, "tp2_gap": 2.5, "trail_r": 0.5}` |
| 2 | 6 | 2.242 | 49 | $2,459.34 | `{"breakeven_r": 1.0, "candle_body_ratio_max": 0.36253663929417146, "candle_wick_ratio_min": 3.8405478769015007, "min_risk_scale": 1.5999763486291623, "split_targets": true, "stop_buffer_scale": 0.5431461647845467, "touch_scale": 0.9740519146488587, "tp1_fraction": 0.25, "tp1_rr": 1.5, "tp2_gap": 2.5, "trail_r": 0.75}` |
| 3 | 0 | 1.826 | 66 | $2,199.99 | `{"breakeven_r": 1.0, "candle_body_ratio_max": 0.3, "candle_wick_ratio_min": 2.0, "min_risk_scale": 1.0, "split_targets": true, "stop_buffer_scale": 1.0, "touch_scale": 1.0, "tp1_fraction": 0.5, "tp1_rr": 3.0, "tp2_gap": 1.0, "trail_r": 0.5}` |
| 4 | 5 | 1.779 | 50 | $1,230.94 | `{"breakeven_r": 0.5, "candle_body_ratio_max": 0.48233103293687846, "candle_wick_ratio_min": 1.084235675120401, "min_risk_scale": 1.6730368309398818, "rr": 1.5, "split_targets": false, "stop_buffer_scale": 0.534962007374769, "target_mode": "opposite_swing", "touch_scale": 0.5230767229789541, "trail_r": 0.5}` |
| 5 | 7 | 1.629 | 55 | $1,159.61 | `{"breakeven_r": 0.5, "candle_body_ratio_max": 0.37921008458911576, "candle_wick_ratio_min": 2.977516313823321, "min_risk_scale": 1.1402465277785279, "split_targets": true, "stop_buffer_scale": 1.9754286702293848, "touch_scale": 0.8446720330560296, "tp1_fraction": 0.25, "tp1_rr": 2.0, "tp2_gap": 2.5, "trail_r": 0.5}` |

### Mutanabby

```json
{
  "atr_risk_multiplier": 0.8,
  "breakeven_r": 0.0,
  "exit_on_opposite_signal": false,
  "risk_atr_length": 11,
  "sensitivity": 5.75,
  "split_targets": true,
  "supertrend_atr_length": 7,
  "tp1_fraction": 0.25,
  "tp1_rr": 3.5,
  "tp2_gap": 1.5,
  "trail_r": 0.0,
  "trend_sma_length": 15
}
```

Top five training trials:

| Rank | Trial | Train Sharpe | Trades | Net P/L | Parameters |
| ---: | ---: | ---: | ---: | ---: | --- |
| 1 | 14 | 2.002 | 87 | $2,766.39 | `{"atr_risk_multiplier": 0.8, "breakeven_r": 0.0, "exit_on_opposite_signal": false, "risk_atr_length": 11, "sensitivity": 5.75, "split_targets": true, "supertrend_atr_length": 7, "tp1_fraction": 0.25, "tp1_rr": 3.5, "tp2_gap": 1.5, "trend_sma_length": 15}` |
| 2 | 15 | 1.048 | 88 | $1,402.09 | `{"atr_risk_multiplier": 0.8, "breakeven_r": 0.0, "exit_on_opposite_signal": false, "risk_atr_length": 11, "sensitivity": 5.5, "split_targets": true, "supertrend_atr_length": 12, "tp1_fraction": 0.25, "tp1_rr": 3.5, "tp2_gap": 1.0, "trend_sma_length": 15}` |
| 3 | 0 | 0.991 | 76 | $1,226.26 | `{"atr_risk_multiplier": 1.0, "breakeven_r": 0.0, "exit_on_opposite_signal": false, "risk_atr_length": 14, "sensitivity": 6.0, "split_targets": true, "supertrend_atr_length": 11, "tp1_fraction": 0.5, "tp1_rr": 3.0, "tp2_gap": 1.0, "trend_sma_length": 13}` |
| 4 | 19 | 0.924 | 79 | $1,200.01 | `{"atr_risk_multiplier": 1.2000000000000002, "breakeven_r": 0.0, "exit_on_opposite_signal": false, "risk_atr_length": 12, "sensitivity": 5.5, "split_targets": true, "supertrend_atr_length": 8, "tp1_fraction": 0.25, "tp1_rr": 3.0, "tp2_gap": 2.0, "trend_sma_length": 26}` |
| 5 | 11 | 0.886 | 57 | $589.46 | `{"atr_risk_multiplier": 1.6, "breakeven_r": 0.0, "exit_on_opposite_signal": false, "risk_atr_length": 22, "sensitivity": 6.75, "split_targets": true, "supertrend_atr_length": 7, "tp1_fraction": 0.5, "tp1_rr": 1.0, "tp2_gap": 2.5, "trend_sma_length": 48}` |

## Interpretation and limitations

This is a clean chronological holdout, but it is still one historical split. A higher test Sharpe is evidence of generalization, not proof. The search evaluates many parameter combinations, transaction costs are approximations, fixed-dollar risk is not a full account-equity simulation, and live fills can differ materially. Before changing live settings, repeat the result over several walk-forward folds and forward-test it on demo.

Total runtime: 1568.9 seconds.

Reproduce from `backend/`:

```powershell
python backtests/optuna_sharpe.py --trials 20 --trendline-trials 8 --train-fraction 0.7 --lookback-days 240 --seed 42 --min-trades 15
```
