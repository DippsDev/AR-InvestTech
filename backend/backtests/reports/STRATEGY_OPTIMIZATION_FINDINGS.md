# Strategy Optimization Findings

Generated: 2026-09-09

## Executive summary

This report consolidates the baseline benchmarks, broad Optuna optimization, Trendline decision-tree analysis, unrestricted Trendline walk-forward study, SVM-guided walk-forward optimization across all three strategies, entry-profit timing, and the exploratory Mutanabby survival-exit study.

> **Current decision: keep all three existing production configurations unchanged.**

The largest findings are:

1. **Broad optimization overfit Trendline and Mutanabby.** Both strategies improved substantially on development data and then deteriorated sharply on unseen data.
2. **The existing Silver Bullet configuration remains stronger than its newer candidates.** A broad Optuna candidate was profitable on its first holdout, but the evidence came from only 10 trades and was inconsistent by symbol. The later SVM-guided candidate was also profitable but inferior to the current baseline.
3. **Reducing the search to three SVM-identified parameters materially reduced the overfitting seen in Trendline.** Its guided candidate improved holdout Sharpe from 2.281 to 2.347, but this was caused largely by one additional DE30m trade and is not strong enough for promotion.
4. **SVM feature discovery was weak for every strategy.** None of the three SVMs cleared both 0.55 balanced accuracy and 0.55 ROC AUC. Their parameter rankings are hypotheses, not reliable causal findings.
5. **Silver Bullet has a serious sample-size limitation.** It produced only 27 usable development trades for SVM discovery: 18 for fitting and 9 for validation. Its final walk-forward holdout contained only 6 baseline trades.
6. **Mutanabby produced the clearest example of overfitting.** Its guided walk-forward Sharpe improved from -0.820 to 1.345, but final holdout Sharpe collapsed from 0.847 to -1.852 and every symbol deteriorated.
7. **The June–July 2026 holdout has now been inspected repeatedly.** It must be considered consumed for future development. New parameter decisions need a later, genuinely unseen period or live/demo forward data.

8. **A Mutanabby survival exit produced a promising historical-test improvement, but not robust promotion evidence.** Test Sharpe rose from 0.145 to 2.832, yet threshold-validation Sharpe remained negative and the gain was concentrated in JP225m.

## Scope and experimental timeline

All studies used the repository's current live portfolios and per-symbol overrides:

| Strategy | Portfolio |
| --- | --- |
| Silver Bullet | XAUUSDm, USTECm |
| Trendline | DE30m, USDJPYm, USTECm |
| Mutanabby | US30m, JP225m, USDJPYm, ETHUSDm |

Unless stated otherwise, results use fixed risk of $100 per trade, a $5 round-trip commission, and spread/slippage scaled to each instrument's median M5 range.

The experiments were performed in this order:

1. Benchmark the current configurations.
2. Run broad Optuna optimization on a single 70/30 chronological split.
3. Fit a decision tree to baseline Trendline wins and losses.
4. Optimize the Trendline backtester so repeated walk-forward studies are practical.
5. Run unrestricted Trendline walk-forward optimization with a final 20% holdout.
6. Fit an SVM to baseline Trendline outcomes and restrict Optuna to three mapped parameters.
7. Apply the same SVM-guided process independently to all three strategies.

### Important partition difference

The first broad Optuna experiment used a 70/30 split with a test start of 2026-05-12. The later walk-forward experiments used an 80/20 development/holdout split; the holdout began on 2026-06-04 for Silver Bullet and Trendline and on 2026-06-05 for Mutanabby.

Therefore, compare each optimized candidate against the baseline reported in the **same experiment**. Do not compare raw Sharpe values across the two partition designs as though they cover identical dates.

## 1. Current baseline configurations

“Baseline” means the strategy configuration currently constructed by the application, including the symbol overrides in `multi_symbol_targets.py`. It does not necessarily mean an untuned default.

### Silver Bullet baseline

Silver Bullet is already the product of earlier historical tuning. Its current core settings include:

- Swing lookback 3 and sweep lookback 10.
- Per-symbol FVG, stop-buffer, and minimum-risk thresholds.
- Midpoint FVG entry.
- Opposite-liquidity target.
- Breakeven at 0.25R, 0.1R trailing distance, and 0.4R early exit.
- XAUUSDm and USTECm as the current live portfolio.

This matters when interpreting later results: the SVM-guided experiment was attempting to improve an already optimized strategy, not a naive Silver Bullet configuration.

### Trendline baseline

The current Trendline configuration uses:

- Swing lookback 3 and maximum steepness ratio 1.0.
- Per-symbol line obstruction, breach, touch, stop-buffer, and minimum-risk thresholds.
- Candle body ceiling 0.30 and wick/body floor 2.0.
- Split targets at 3R and 4R, split 50/50.
- Breakeven at 1R and trailing distance 0.5R.

### Mutanabby baseline

The current portfolio configuration uses:

- Sensitivity 6.0.
- SuperTrend ATR length 11 and trend SMA length 13.
- Risk ATR length 14 and ATR risk multiplier 1.0.
- Split targets at 3R and 4R, split 50/50.
- No breakeven, trailing stop, or opposite-signal exit.

### Baseline on the original 70/30 experiment

| Strategy | Partition | Sharpe | Trades | Net P/L | Profit factor | Max drawdown | Win rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Silver Bullet | Train | 0.873 | 23 | $355.52 | 1.40 | $383.50 | 56.5% |
| Silver Bullet | Holdout | 0.609 | **10** | $135.07 | 1.27 | $377.45 | 70.0% |
| Trendline | Train | 1.826 | 66 | $2,199.99 | 1.70 | $604.66 | 56.1% |
| Trendline | Holdout | 1.233 | 30 | $482.21 | 1.33 | $449.40 | 43.3% |
| Mutanabby | Train | 0.991 | 76 | $1,226.26 | 1.23 | $1,586.47 | 32.9% |
| Mutanabby | Holdout | -0.010 | 27 | $15.44 | 1.01 | $749.95 | 29.6% |

## 2. Broad Optuna optimization

The first Optuna experiment maximized annualized daily-P/L Sharpe on the first 70% of the dates and evaluated the winner once on the final 30%. It used 20 trials for Silver Bullet and Mutanabby and only 8 Trendline trials because the original Trendline backtester was still slow.

### Aggregate result

| Strategy | Configuration | Train Sharpe | Train trades | Holdout Sharpe | Holdout trades | Holdout net | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Silver Bullet | Current | 0.873 | 23 | 0.609 | **10** | $135.07 | Baseline |
| Silver Bullet | Broad Optuna | 2.023 | 40 | 1.313 | **10** | $179.54 | Positive but insufficient evidence |
| Trendline | Current | 1.826 | 66 | 1.233 | 30 | $482.21 | Baseline |
| Trendline | Broad Optuna | 3.513 | 57 | -1.409 | 21 | -$323.07 | Overfit; reject |
| Mutanabby | Current | 0.991 | 76 | -0.010 | 27 | $15.44 | Baseline |
| Mutanabby | Broad Optuna | 2.002 | 87 | -2.736 | 32 | -$970.53 | Overfit; reject |

### Silver Bullet finding

Silver Bullet was the only broad Optuna candidate to improve both train and holdout Sharpe. However, the holdout had only 10 trades:

- XAUUSDm deteriorated from +$56.98 on 2 trades to -$1.16 on 4 trades.
- USTECm improved from +$78.09 on 8 trades to +$180.71 on 6 trades.

The aggregate gain therefore came from USTECm while XAUUSDm weakened. Ten trades are not enough to distinguish a durable improvement from trade-order luck, so the candidate was not promoted.

The broad candidate's main changes were swing lookback 4, near-edge entry, FVG scale 0.777, stop-buffer scale 1.653, and minimum-risk scale 0.902.

### Trendline finding

Trendline's training Sharpe nearly doubled, but holdout performance changed from +$482.21 to -$323.07. DE30m and USDJPYm both deteriorated. This was clear parameter overfitting.

The broad search varied many interacting choices at once: candle rules, touch/risk thresholds, target structure, breakeven, trailing, and other settings. The selected candidate had no stable out-of-sample edge.

### Mutanabby finding

Mutanabby's train Sharpe improved from 0.991 to 2.002, while holdout Sharpe fell from -0.010 to -2.736. Holdout net P/L dropped by approximately $986. Every symbol except JP225m had a worse Sharpe, and the aggregate result was decisively negative.

## 3. Trendline decision-tree investigation

A class-balanced decision tree with maximum depth 8 was fitted to entry-time characteristics of baseline Trendline trades.

The training data suggested four notable characteristics:

- Directional candle body.
- Distance in bars between the trendline anchors.
- Six-hour return aligned to trade direction.
- Trendline slope aligned to trade direction.

However, the model failed its holdout:

| Metric | Result |
| --- | ---: |
| Training samples | 66 |
| Holdout samples | 30 |
| Holdout balanced accuracy | 0.389 |
| Holdout ROC AUC | 0.432 |
| Majority-class accuracy | 0.567 |

The hypothetical tree filter made performance worse: it retained 13 trades, reduced win rate to 30.8%, produced -$174.44, and had Sharpe -0.947. The tree is useful only for generating hypotheses; it should not become a live entry filter.

## 4. Trendline backtester optimization

The original Trendline engine repeatedly rescanned the complete bar prefix for swing highs and lows, creating approximately quadratic work as history grew. It was changed to maintain confirmed swing points incrementally for historical arrays.

- USTECm 180-day benchmark: approximately 59.5 seconds before and 0.26 seconds after.
- Approximate speedup: **229×**.
- The old and new engines produced the same 21 ordered trades in a direct parity comparison.
- The live adapter retains the stateless path because its rolling MT5 bar indices shift between cycles.

This speedup made real walk-forward Trendline studies practical and reduced a four-fold, 40-trial portfolio study to about 29 seconds.

## 5. Unrestricted Trendline walk-forward optimization

The next Trendline study used four chronological forward windows inside the first 80% of history and evaluated the winner on a final untouched 20% holdout. It searched substantially more parameters than the later SVM-guided study.

| Configuration | Walk-forward Sharpe | Trades | Walk-forward net | Holdout Sharpe | Holdout trades | Holdout net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Current Trendline | 2.213 | 31 | $1,725.03 | 2.281 | 19 | $675.21 |
| Unrestricted Optuna | 3.389 | 24 | $1,798.71 | 0.551 | 18 | $158.45 |

Despite a large improvement in the selection windows, holdout Sharpe fell by 1.730 and holdout net P/L fell by $516.76. USDJPYm changed from +$450.17 to -$315.14, while USTECm fell from -$31.28 to -$210.00. This candidate was rejected.

This result motivated a smaller search space selected from baseline trade characteristics.

## 6. SVM-guided parameter selection

For each strategy, a class-balanced linear-kernel SVM was fitted to early development-period baseline trades. Permutation importance was measured on later development trades. Only entry-time features were allowed; future bars, exit information, and P/L were excluded from the predictors.

Actionable features were mapped to existing strategy parameters, and Optuna was limited to at most three parameters per strategy. Context features such as hour, symbol, or recent returns were reported but could not select a parameter unless an existing strategy control mapped to them.

### SVM evidence quality

| Strategy | Usable development trades | SVM fit | SVM validation | Balanced accuracy | ROC AUC | Assessment |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Silver Bullet | **27** | **18** | **9** | 0.500 | 0.333 | Too small and no demonstrated discrimination |
| Trendline | 77 | 53 | 24 | 0.621 | 0.514 | Mixed and weak |
| Mutanabby | 84 | 58 | 26 | 0.523 | 0.511 | Near random |

> **Big warning:** feature importance is not trustworthy merely because an SVM can calculate it. The model must first demonstrate out-of-sample discrimination. None of these SVMs cleared both chosen diagnostic thresholds, so every mapping remains exploratory.

### Parameters selected by SVM evidence

| Strategy | Parameters allowed into Optuna | Primary feature evidence |
| --- | --- | --- |
| Silver Bullet | `fvg_scale`, `stop_buffer_scale`, `min_risk_scale` | FVG size, fill gap, and risk relative to recent range |
| Trendline | `candle_body_ratio_max`, `swing_lookback`, `candle_wick_ratio_min` | Candle body, anchor span/age, and wick geometry |
| Mutanabby | `risk_atr_length`, `supertrend_atr_length`, `atr_risk_multiplier` | ATR/risk and SuperTrend distance features |

Mutanabby's selected parameter scores were only 0.002–0.005 and smaller than their permutation uncertainty. They should be viewed as a forced ranking of weak signals, not convincing importance.

## 7. SVM-guided walk-forward optimization

Each strategy received its own four-fold, 30-trial Optuna study. Every unselected parameter remained at its current baseline value.

### Combined results

| Strategy | Configuration | Walk-forward Sharpe | WF trades | WF net | Holdout Sharpe | Holdout trades | Holdout net | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Silver Bullet | Current | -0.129 | **12** | -$36.81 | **2.869** | **6** | **$379.80** | Keep |
| Silver Bullet | SVM-guided | 1.105 | 22 | $331.24 | 2.259 | 10 | $342.32 | Reject versus baseline |
| Trendline | Current | 2.213 | 31 | $1,725.03 | 2.281 | 19 | $675.21 | Keep |
| Trendline | SVM-guided | 2.370 | 32 | $1,858.52 | 2.347 | 20 | $702.62 | Exploratory only |
| Mutanabby | Current | -0.820 | 46 | -$526.15 | **0.847** | 15 | **$254.62** | Keep |
| Mutanabby | SVM-guided | 1.345 | 44 | $897.40 | **-1.852** | 16 | **-$401.09** | Reject |

### Silver Bullet interpretation

The candidate remained profitable on the holdout, so it retained some absolute edge, but it did **not** beat the current optimized baseline:

| Holdout metric | Current | Guided candidate |
| --- | ---: | ---: |
| Sharpe | **2.869** | 2.259 |
| Net P/L | **$379.80** | $342.32 |
| Profit factor | **4.62** | 2.53 |
| Max drawdown | **$105.00** | $210.00 |
| Win rate | **83.3%** | 70.0% |

The symbol split was inconsistent:

- USTECm improved from +$343.51 to +$404.67.
- XAUUSDm deteriorated from +$36.29 to -$62.35.

Most importantly, the current holdout contains only 6 trades and the candidate only 10. Sharpe, profit factor, and win rate are extremely unstable at this sample size. The correct description is “profitable out of sample but inferior to the current baseline,” not successful promotion evidence.

The selected candidate mostly widened setup admission by reducing `fvg_scale` to 0.601; stop-buffer and minimum-risk scales remained near 1.0.

### Trendline interpretation

Trendline was the only strategy whose guided candidate improved both the walk-forward aggregate and the final holdout:

- Holdout Sharpe: 2.281 to 2.347.
- Holdout P/L: $675.21 to $702.62.
- Holdout trades: 19 to 20.
- Profit factor: 1.85 to 1.89.

The improvement was narrow: DE30m added one profitable trade, while USDJPYm and USTECm were unchanged. Swing lookback stayed at 3, the candle-body ceiling remained near 0.30, and the meaningful change was loosening the wick/body threshold from 2.0 to approximately 1.63.

This is consistent with reduced overfitting, but it is not enough evidence to update production. The SVM ROC AUC was only 0.514, one forward fold remained negative, and one trade accounts for most of the holdout difference.

### Mutanabby interpretation

Mutanabby produced the strongest warning:

- Walk-forward Sharpe improved from -0.820 to 1.345.
- Walk-forward P/L improved from -$526.15 to +$897.40.
- Holdout Sharpe then fell from 0.847 to -1.852.
- Holdout P/L fell from +$254.62 to -$401.09.

Every holdout symbol deteriorated:

| Symbol | Current net | Guided net |
| --- | ---: | ---: |
| US30m | $676.89 | $571.33 |
| JP225m | -$315.00 | -$496.75 |
| USDJPYm | -$89.74 | -$420.00 |
| ETHUSDm | -$17.52 | -$55.66 |

The selected risk ATR length 12, SuperTrend ATR length 17, and ATR multiplier 1.1 fitted the development windows but did not generalize. The existing Mutanabby configuration should remain unchanged.

## 8. What the experiments taught us about overfitting

### Restricting parameter count helps, but does not solve the problem

The unrestricted Trendline walk-forward candidate reduced holdout Sharpe from 2.281 to 0.551. The three-parameter SVM-guided candidate produced 2.347. This is encouraging evidence that a smaller hypothesis space can reduce overfitting.

However, Mutanabby still overfit badly with only three parameters. Parameter count is only one source of overfitting; weak feature evidence, small samples, unstable regimes, and repeated candidate selection also matter.

### Model-guided optimization requires a useful model

An SVM cannot provide trustworthy importance when it cannot reliably distinguish winners from losers. Silver Bullet's 0.500 balanced accuracy / 0.333 AUC and Mutanabby's 0.523 / 0.511 provide no strong basis for parameter selection. Trendline's 0.621 balanced accuracy is more interesting, but its 0.514 AUC remains weak.

### The final holdout outranks the optimization score

Both Silver Bullet and Mutanabby improved in the walk-forward selection windows and then lost ground against their baselines on the holdout. The development objective answers “what fitted these development regimes?” The holdout answers the more important question: “did that choice survive data that played no role in selecting it?”

### Per-symbol consistency matters

Portfolio aggregation can hide deterioration. Silver Bullet's USTECm improvement masked XAUUSDm losses. Mutanabby's aggregate development improvement failed across every holdout symbol. A candidate should not be promoted solely because one symbol dominates aggregate P/L.

### Existing baselines may already be optimized

Silver Bullet is the clearest example. Its current configuration already incorporates prior optimization and per-symbol selection. Re-optimizing it adds another layer of multiple testing and should be expected to produce increasingly fragile apparent improvements.

## 9. Mutanabby survival-exit study

A regularized discrete-time logistic hazard model was trained to estimate whether the current completed H1 bar was the last profitable peak before a baseline Mutanabby trade's normal exit. The model was fitted on 55 early-period trades; its exit threshold was selected on 21 later development trades; and the resulting policy was replayed once on 27 baseline historical-test trades.

| Partition | Configuration | Sharpe | Trades | Net P/L | Max drawdown |
| --- | --- | ---: | ---: | ---: | ---: |
| Threshold validation | Baseline | -1.587 | 21 | -$428.06 | $1,209.79 |
| Threshold validation | Survival exit | -1.436 | 37 | -$500.39 | $840.00 |
| Historical test | Baseline | 0.145 | 27 | $62.74 | $749.95 |
| Historical test | Survival exit | 2.832 | 33 | $1,090.51 | $427.87 |

The selected threshold was 0.30: an otherwise-open profitable trade became eligible to exit when estimated peak-survival probability fell to 30% or lower, with execution at the next H1 open. All 12 survival exits in the historical test realized a profit.

The result is encouraging but fragile:

- Threshold-validation performance improved only slightly and remained loss-making.
- Most of the historical-test gain came from JP225m, which changed from -$749.95 to +$826.31.
- US30m and ETHUSDm both earned less under the policy; USDJPYm was unchanged.
- The hazard validation ROC AUC was 0.954, but only 15 peak events existed in validation and peak events represented 1.52% of person-period rows.
- Earlier exits changed later signal availability, increasing test trades from 27 to 33. The full event loop was replayed to capture that interaction correctly.
- The May-July test period overlaps dates already examined in prior studies, so it is not fresh confirmation.

The policy remains research-only. It should be frozen and demo-forward-tested on genuinely new data before any production consideration.

## 10. Decisions and next steps

### Production decisions

- **Silver Bullet:** keep the current, already optimized configuration.
- **Trendline:** keep the current configuration. Preserve the wick-threshold candidate as a research hypothesis only.
- **Mutanabby:** keep the current configuration and reject both broad and SVM-guided candidates.
- **Mutanabby survival exit:** preserve as a frozen research candidate; do not deploy before new forward evidence.
- **Decision-tree filter:** do not deploy.

### Evidence needed before reconsidering

1. Accumulate a genuinely new forward period. The currently inspected June–July holdout cannot be reused as proof for another iteration.
2. Prioritize more Silver Bullet trades. Six to ten holdout trades are inadequate for stable Sharpe or profit-factor estimates. There is no magic minimum, but validation should contain at least several dozen trades and span multiple regimes before supporting a parameter change.
3. Refit feature models only after more baseline outcomes exist. A larger sample is more valuable than trying additional classifiers on the same small dataset.
4. Keep future searches narrow and predeclare the mapping, ranges, objective, and promotion criteria before viewing the next holdout.
5. Require improvement in risk-adjusted return, drawdown, and per-symbol behavior—not Sharpe alone.
6. Demo forward-test any surviving candidate with realistic broker fills before changing live configuration.

## 11. Limitations

- Sharpe is calculated from fixed-risk daily P/L with zero-P/L source dates included; it is not a full account-equity simulation.
- Costs are approximations and live spread, slippage, rejected orders, and latency may differ.
- The search compares many alternatives, creating selection bias even with walk-forward folds.
- SVM permutation importance measures association, not the causal effect of changing a strategy parameter.
- Parameter-to-feature mappings are informed hypotheses rather than learned counterfactual effects.
- The Trendline backtester currently tracks one open trade at a time even though the live configuration can permit concurrent positions.
- Very small per-symbol and per-fold trade counts make Sharpe, win rate, and profit factor unstable.

## Source artifacts

- [ENTRY_PROFIT_TIMING.md](ENTRY_PROFIT_TIMING.md) - first-profit timing across all three strategies.
- [MUTANABBY_SURVIVAL_EXIT_REPORT.md](MUTANABBY_SURVIVAL_EXIT_REPORT.md) - chronological Mutanabby peak-survival exit study.
- [OPTUNA_SHARPE_REPORT.md](../OPTUNA_SHARPE_REPORT.md) — original 70/30 baseline and broad Optuna study.
- [TRENDLINE_DECISION_TREE_REPORT.md](../TRENDLINE_DECISION_TREE_REPORT.md) — Trendline win/loss decision-tree analysis.
- [TRENDLINE_WALK_FORWARD_REPORT.md](../TRENDLINE_WALK_FORWARD_REPORT.md) — unrestricted Trendline walk-forward study.
- [TRENDLINE_SVM_GUIDED_OPTUNA_REPORT.md](../TRENDLINE_SVM_GUIDED_OPTUNA_REPORT.md) — first Trendline-only SVM-guided study.
- [ALL_STRATEGIES_SVM_GUIDED_REPORT.md](../ALL_STRATEGIES_SVM_GUIDED_REPORT.md) — final SVM-guided study across all strategies.
