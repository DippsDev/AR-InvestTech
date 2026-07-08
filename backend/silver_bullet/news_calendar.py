"""
High-impact US economic event dates that should be avoided for intraday trading.
Covers NFP, FOMC, CPI, and GDP releases for 2022-2026, plus FOMC only for 2027
(BLS/BEA had not yet published their 2027 schedules as of this writing).

Sources:
  - BLS Employment Situation release schedule
  - Federal Reserve FOMC meeting calendar (statement/rate-decision date)
  - BLS Consumer Price Index release schedule
  - BEA Gross Domestic Product (advance estimate) release schedule

When the calendar runs out, update it with the new year's release dates.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Union

# fmt: off
HIGH_IMPACT_DATES: frozenset[str] = frozenset({
    # ── 2022 ──────────────────────────────────────────────────────────
    # NFP
    "2022-01-07", "2022-02-04", "2022-03-04", "2022-04-01",
    "2022-05-06", "2022-06-03", "2022-07-08", "2022-08-05",
    "2022-09-02", "2022-10-07", "2022-11-04", "2022-12-02",
    # FOMC
    "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27",
    "2022-09-21", "2022-11-02", "2022-12-14",
    # CPI
    "2022-01-12", "2022-02-10", "2022-03-10", "2022-04-12",
    "2022-05-11", "2022-06-10", "2022-07-13", "2022-08-10",
    "2022-09-13", "2022-10-13", "2022-11-10", "2022-12-13",

    # ── 2023 ──────────────────────────────────────────────────────────
    # NFP
    "2023-01-06", "2023-02-03", "2023-03-10", "2023-04-07",
    "2023-05-05", "2023-06-02", "2023-07-07", "2023-08-04",
    "2023-09-01", "2023-10-06", "2023-11-03", "2023-12-08",
    # FOMC
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # CPI
    "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12",
    "2023-05-10", "2023-06-13", "2023-07-12", "2023-08-10",
    "2023-09-13", "2023-10-12", "2023-11-14", "2023-12-12",
    # GDP (advance)
    "2023-01-26", "2023-04-27", "2023-07-27", "2023-10-26",

    # ── 2024 ──────────────────────────────────────────────────────────
    # NFP
    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05",
    "2024-05-03", "2024-06-07", "2024-07-05", "2024-08-02",
    "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06",
    # FOMC
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # CPI
    "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10",
    "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14",
    "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
    # GDP (advance)
    "2024-01-25", "2024-04-25", "2024-07-25", "2024-10-30",

    # ── 2025 ──────────────────────────────────────────────────────────
    # NFP (BLS Employment Situation release dates)
    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04",
    "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01",
    "2025-09-05", "2025-10-03", "2025-11-07", "2025-12-05",
    # FOMC (rate-decision / statement release dates)
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # CPI (BLS CPI release dates; 2025 had some holiday/shutdown shifts)
    "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13",
    "2025-06-11", "2025-07-15", "2025-08-12", "2025-09-11",
    "2025-10-24", "2025-11-13", "2025-12-10",
    # GDP (advance estimates)
    "2025-01-30", "2025-04-30", "2025-07-30", "2025-10-30",

    # ── 2026 ──────────────────────────────────────────────────────────
    # NFP (BLS Employment Situation release dates)
    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03",
    "2026-05-08", "2026-06-05", "2026-07-02", "2026-08-07",
    "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    # FOMC (rate-decision / statement release dates)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    # CPI (BLS CPI release dates)
    "2026-01-13", "2026-02-13", "2026-03-11", "2026-04-10",
    "2026-05-12", "2026-06-10", "2026-07-14", "2026-08-12",
    "2026-09-11", "2026-10-14", "2026-11-10", "2026-12-10",
    # GDP (advance estimates)
    "2026-02-20", "2026-04-30", "2026-07-30", "2026-10-29",

    # ── 2027 ──────────────────────────────────────────────────────────
    # FOMC only (tentative schedule announced 2025-09-05; second day of each
    # two-day meeting is the statement/rate-decision date):
    # https://www.federalreserve.gov/newsevents/pressreleases/monetary20250905a.htm
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
    "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
    # NFP / CPI / GDP for 2027: BLS and BEA had not published their 2027
    # release schedules as of 2026-07-06. Add them here once published
    # (BLS usually publishes in Q4 of the prior year) — see
    # https://www.bls.gov/schedule/news_release/empsit.htm and
    # https://www.bls.gov/schedule/news_release/cpi.htm
})
# fmt: on


def is_news_day(value: Union[str, date, datetime]) -> bool:
    """
    Return True if the supplied date (str 'YYYY-MM-DD', date, or datetime)
    is a known high-impact US macro release day.
    """
    if isinstance(value, str):
        date_str = value
    elif isinstance(value, datetime):
        date_str = value.date().isoformat()
    elif isinstance(value, date):
        date_str = value.isoformat()
    else:
        raise TypeError(f"Expected str, date or datetime; got {type(value).__name__}")
    return date_str in HIGH_IMPACT_DATES
