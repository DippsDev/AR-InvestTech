# Entry-to-First-Profit Distribution

Generated: 2026-09-09T18:15:58.377187+00:00

## Big findings

- **Mutanabby had the highest observed-profit rate:** 77.8% of entries became profitable before exit.
- **Silver Bullet had the shortest median wall-clock time:** 5 min among trades that became profitable.
- **All 21 profitable Silver Bullet entries crossed break-even within three M5 bars (15 minutes).** No later first-profit event was observed.
- **48 of 96 Trendline entries (50.0%) were profitable by the first H1 close.**
- **46 of 68 Mutanabby losers (67.6%) were profitable first.** Its high initial-profit rate did not translate into a high final win rate.
- A losing trade can still spend time in profit before reversing. The loser-to-profit rate below is therefore important when evaluating entry quality and management rules.
- Results are descriptive baseline behavior, not evidence that a new exit rule will improve performance.

## Definition

A trade becomes profitable at the first completed bar close where marked P/L is above zero after the modeled adverse fill and one $5.00 round-trip commission. A profitable TP1 or final booked exit can establish profit earlier than a qualifying close.

The entry bar close is included. The exit-bar close is excluded for intrabar stop/target exits because OHLC data cannot prove whether that close happened before or after the exit. This makes the measurement conservative. Time is quantized to each strategy's source bars: Silver Bullet uses M5; Trendline and Mutanabby use H1.

History: current baseline configurations over the final 240 calendar days available for each live portfolio. This is a descriptive full-period analysis; no parameters were optimized and no train/test selection was performed.

## Headline statistics

| Strategy | Timeframe | Trades | Ever profitable | Never observed profitable | Median time | P25–P75 time | Median bars | Losing trades ever profitable |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Silver Bullet | 5 min | 33 | 21 (63.6%) | 12 (36.4%) | 5 min | 5 min–10 min | 1.0 | 1/13 (7.7%) |
| Trendline | 60 min | 96 | 60 (62.5%) | 36 (37.5%) | 1.0 h | 1.0 h–1.0 h | 1.0 | 10/46 (21.7%) |
| Mutanabby | 60 min | 99 | 77 (77.8%) | 22 (22.2%) | 1.0 h | 1.0 h–3.0 h | 1.0 | 46/68 (67.6%) |

## Wall-clock distribution

Percentages use all entries as the denominator, so the rows—including `Never`—sum to 100% per strategy.

| Time to first profit | Silver Bullet | Trendline | Mutanabby |
| --- | ---: | ---: | ---: |
| Within 1 hour | 21 (63.6%) | 48 (50.0%) | 46 (46.5%) |
| 1–4 hours | 0 (0.0%) | 10 (10.4%) | 23 (23.2%) |
| 4–12 hours | 0 (0.0%) | 1 (1.0%) | 4 (4.0%) |
| 12–24 hours | 0 (0.0%) | 1 (1.0%) | 3 (3.0%) |
| 1–3 days | 0 (0.0%) | 0 (0.0%) | 1 (1.0%) |
| More than 3 days | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) |
| Never observed profitable | 12 (36.4%) | 36 (37.5%) | 22 (22.2%) |

## Bar-count distribution

Bar counts compare how many strategy decisions elapsed, while wall-clock time reflects the M5/H1 timeframe difference.

| Bars to first profit | Silver Bullet | Trendline | Mutanabby |
| --- | ---: | ---: | ---: |
| 1 bar | 15 (45.5%) | 48 (50.0%) | 46 (46.5%) |
| 2–3 bars | 6 (18.2%) | 10 (10.4%) | 17 (17.2%) |
| 4–6 bars | 0 (0.0%) | 1 (1.0%) | 8 (8.1%) |
| 7–12 bars | 0 (0.0%) | 0 (0.0%) | 2 (2.0%) |
| 13–24 bars | 0 (0.0%) | 1 (1.0%) | 3 (3.0%) |
| More than 24 bars | 0 (0.0%) | 0 (0.0%) | 1 (1.0%) |
| Never observed profitable | 12 (36.4%) | 36 (37.5%) | 22 (22.2%) |

## Results by symbol

### Silver Bullet

| Symbol | Trades | Ever profitable | Never | Median time | Median bars | Losing trades ever profitable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| USTECm | 18 | 9 (50.0%) | 9 | 5 min | 1.0 | 0/9 (0.0%) |
| XAUUSDm | 15 | 12 (80.0%) | 3 | 5 min | 1.0 | 1/4 (25.0%) |

### Trendline

| Symbol | Trades | Ever profitable | Never | Median time | Median bars | Losing trades ever profitable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DE30m | 38 | 27 (71.1%) | 11 | 1.0 h | 1.0 | 5/16 (31.2%) |
| USDJPYm | 26 | 15 (57.7%) | 11 | 1.0 h | 1.0 | 4/15 (26.7%) |
| USTECm | 32 | 18 (56.2%) | 14 | 1.0 h | 1.0 | 1/15 (6.7%) |

### Mutanabby

| Symbol | Trades | Ever profitable | Never | Median time | Median bars | Losing trades ever profitable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ETHUSDm | 25 | 22 (88.0%) | 3 | 2.0 h | 2.0 | 13/16 (81.2%) |
| JP225m | 29 | 19 (65.5%) | 10 | 1.0 h | 1.0 | 12/22 (54.5%) |
| US30m | 18 | 14 (77.8%) | 4 | 1.0 h | 1.0 | 8/12 (66.7%) |
| USDJPYm | 27 | 22 (81.5%) | 5 | 1.0 h | 1.0 | 13/18 (72.2%) |

## Interpretation cautions

- `Never observed profitable` does not prove price never moved favorably intrabar. It means no unambiguous profitable close or booked exit was observed before closure.
- Bar timestamps represent interval starts. Reported wall-clock time is an upper-bound at bar resolution and can overstate the true crossing time by up to one bar.
- One commission is used for a consistent entry-quality threshold. Split positions and partial exits can incur different realized commission accounting.
- Silver Bullet has far fewer trades than the other strategies, so its percentages and quantiles are less stable.
- This analysis describes existing entries. It does not account for opportunity cost, maximum adverse excursion, or whether waiting longer improves final expectancy.
- The Mutanabby give-back pattern motivates a separate maximum-favorable-excursion and exit-policy study; it does not by itself prove that an earlier exit would improve expectancy.

The accompanying CSV contains one row per trade for alternative bins or survival-style analysis.
