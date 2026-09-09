# Mutanabby Survival-Exit Study

Generated: 2026-09-09T18:50:15.128774+00:00

## Conclusion

The survival exit is promising but not robust enough to deploy. It improved this historical test, but threshold-validation performance remained negative and the test gain was concentrated in JP225m. A genuinely new forward period is required.

The model selected survival threshold `0.30`. Historical-test Sharpe changed from **0.145** to **2.832**.

> **This is exploratory validation, not a fresh test.** The final dates overlap the May-July period already inspected during prior optimization work. They cannot provide independent confirmation for a production change.

## Big findings

- The hazard model ranked peak bars well on later data (ROC AUC 0.954), but its class-balanced accuracy was only 0.566. The 1.52% event prevalence makes raw accuracy misleading.
- Threshold validation improved Sharpe only from -1.587 to -1.436; **both configurations still lost money** in that period.
- The historical-test result was much stronger: Sharpe 0.145 to 2.832, net P/L $62.74 to $1,090.51, and drawdown $749.95 to $427.87.
- The improvement was concentrated in **JP225m**. US30m and ETHUSDm earned less under the policy, while USDJPYm was unchanged.
- The policy made 12 test-period survival exits and all 12 were profitable, but the baseline test contained only 27 trades.

## Experimental design

- Model fit: 2025-11-25 to 2026-03-21.
- Threshold selection: 2026-03-22 to 2026-05-11.
- Historical test: 2026-05-12 to 2026-07-22.
- Model: regularized discrete-time logistic hazard model.
- Event: the bar containing a baseline trade's highest positive commission-adjusted close before its normal exit. Trades without a positive close are censored.
- Dynamic inputs: elapsed time, current R, running MFE, drawdown from MFE, momentum, volatility, target/stop distance, RSI, signal strength, symbol, and direction.
- At each completed H1 bar, predicted hazards are accumulated into survival probability. If survival is below the selected threshold and marked P/L is positive, the position exits at the next H1 open.
- A threshold of 0.30 means exit eligibility begins when the model estimates at most 30% probability that the profitable peak still lies ahead (equivalently, at least 70% cumulative probability it has occurred).
- Threshold selection used three chronological validation blocks and maximized pooled daily-P/L Sharpe minus 0.25 times fold-Sharpe volatility.
- The complete event loop was replayed, allowing earlier exits to change later trade availability.

## Model sample

| Partition | Baseline trades | Person-period rows | Peak events | Event rate |
| --- | ---: | ---: | ---: | ---: |
| Model fit | 55 | 2752 | 41 | 1.49% |
| Threshold validation | 21 | 984 | 15 | 1.52% |

The number of rows is not the effective sample size: repeated bars from one trade are correlated. The trade and event counts are the important limits.

## Hazard-model validation

| Metric | Result |
| --- | ---: |
| Accuracy at 0.50 hazard | 0.986 |
| Balanced accuracy | 0.566 |
| ROC AUC | 0.954 |
| Brier score | 0.012 |
| Peak-event prevalence | 1.52% |

### Largest standardized coefficients

Positive coefficients increase the estimated probability that the ultimate profitable peak occurs on the current bar; negative coefficients imply more estimated survival.

| Feature | Coefficient |
| --- | ---: |
| `drawdown_from_mfe_r` | -1.465 |
| `distance_to_target_r` | -0.714 |
| `mfe_r` | -0.682 |
| `distance_to_stop_r` | 0.605 |
| `log_elapsed_bars` | -0.440 |
| `elapsed_bars` | 0.349 |
| `risk_to_range` | -0.344 |
| `momentum_1bar_r` | 0.320 |
| `symbol_USDJPYm` | -0.285 |
| `symbol_ETHUSDm` | 0.234 |
| `symbol_JP225m` | 0.232 |
| `tp1_hit` | 0.191 |

## Threshold selection

| Survival threshold | Objective | Pooled Sharpe | Trades | Survival exits | Fold Sharpes |
| ---: | ---: | ---: | ---: | ---: | --- |
| 0.10 | -3.070 | -2.151 | 34 | 1 | `[-7.222, -1.191, 1.585]` |
| 0.20 | -4.097 | -3.136 | 35 | 1 | `[-7.82, -2.801, 1.585]` |
| 0.30 | -1.754 | -1.436 | 37 | 7 | `[-1.281, -2.966, 0.137]` |
| 0.40 | -2.942 | -2.286 | 40 | 9 | `[-1.815, -5.729, 0.643]` |
| 0.50 | -4.075 | -3.140 | 40 | 9 | `[-2.175, -8.595, 0.27]` |
| 0.60 | -3.756 | -2.314 | 41 | 11 | `[-2.004, -10.215, 3.847]` |
| 0.70 | -2.469 | -1.071 | 43 | 17 | `[-2.08, -7.924, 5.729]` |
| 0.80 | -1.835 | -0.433 | 45 | 21 | `[-1.24, -8.629, 5.093]` |
| 0.90 | -2.005 | -0.639 | 46 | 26 | `[-1.906, -8.586, 4.797]` |
| 0.95 | -3.165 | -1.796 | 46 | 28 | `[-1.965, -10.431, 2.819]` |

## Aggregate results

| Configuration / partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate | Survival exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline / threshold validation | -1.587 | 21 | $-428.06 | 0.71 | $1,209.79 | 33.3% | 0 |
| Survival / threshold validation | -1.436 | 37 | $-500.39 | 0.81 | $840.00 | 32.4% | 7 |
| Baseline / historical test | 0.145 | 27 | $62.74 | 1.03 | $749.95 | 29.6% | 0 |
| Survival / historical test | 2.832 | 33 | $1,090.51 | 1.55 | $427.87 | 42.4% | 12 |

## Historical test by symbol

| Symbol | Baseline Sharpe | Survival Sharpe | Baseline trades | Survival trades | Survival exits | Baseline net | Survival net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| US30m | 1.585 | 0.247 | 5 | 7 | 2 | $361.89 | $52.05 |
| JP225m | -5.673 | 2.850 | 9 | 12 | 6 | $-749.95 | $826.31 |
| USDJPYm | -0.693 | -0.693 | 4 | 4 | 0 | $-89.74 | $-89.74 |
| ETHUSDm | 1.941 | 1.460 | 9 | 10 | 4 | $540.54 | $301.89 |

## Survival-exit behavior

The policy made 12 survival exits in the historical test; 12 (100.0%) closed with positive realized P/L.

The strategy produced more trades under the policy because earlier exits freed the single-position slot for later signals. This is why the study replayed the complete event loop instead of editing baseline exits after the fact.

## Limitations

- The true final peak is known only retrospectively. The survival event is therefore a training label, not an event observable during live trading.
- Baseline stop/target exits create informative censoring and can affect the learned hazard.
- Person-period rows do not create independent samples; the number of trades remains small.
- Survival probabilities from a logistic hazard model are model estimates, not guarantees.
- Threshold comparisons introduce selection bias, even though selection was isolated from the test slice.
- Next-open execution can gap away from the profitable decision close.
- A fresh demo/forward period is mandatory before considering a live management change.

Reproduce from `backend/`:

```powershell
python backtests/mutanabby_survival_exit.py --lookback-days 240 --test-fraction 0.3 --model-fraction 0.7 --stability-penalty 0.25
```
