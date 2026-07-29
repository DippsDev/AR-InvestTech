"""
AR Investments — Mutanabby "Ultimate Algo" Strategy
Source  : Pine v5 indicator, backend/Tradingview Indicator Mutanabby_AI V7.txt
Strategy: SuperTrend(ATR 11, factor 4) flip, filtered by close vs SMA(13)
Entry   : market order on the bar CLOSE that produces the flip
Risk    : stop at signal bar's low/high -/+ ATR(14) x multiplier; target at fixed R
"""
