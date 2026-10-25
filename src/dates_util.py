"""Date rules for the ZentroMart dataset.

Fixed reference date: 20 October 2026 (KB-00.2).
Business days: Monday-Saturday, excluding holidays in data/holidays.csv (KB-00.3).
Return windows: calendar days (RET-2).
Refund timelines: business days counted *from the day after* initiation,
verified against practice questions PQ0008/PQ0022/PQ0027/PQ0028.
"""
from __future__ import annotations

import csv
import os
from datetime import date, timedelta

REFERENCE_DATE = date(2026, 10, 20)

DEFAULT_HOLIDAYS = {
    date(2026, 8, 15), date(2026, 10, 2),
    date(2026, 10, 19), date(2026, 11, 9),
}

MONTHS_EN = ["", "January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"]
MONTHS_HI = ["", "जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून",
             "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]


def load_holidays(data_dir: str | None) -> set[date]:
    if data_dir:
        path = os.path.join(data_dir, "holidays.csv")
        if os.path.exists(path):
            out = set()
            with open(path, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    y, m, d = row["date"].split("-")
                    out.add(date(int(y), int(m), int(d)))
            return out
    return set(DEFAULT_HOLIDAYS)


def is_business_day(d: date, holidays: set[date]) -> bool:
    return d.weekday() != 6 and d not in holidays  # weekday 6 = Sunday


def add_business_days(start: date, n: int, holidays: set[date]) -> date:
    """Date that is n business days after `start` (start itself not counted)."""
    d, counted = start, 0
    while counted < n:
        d += timedelta(days=1)
        if is_business_day(d, holidays):
            counted += 1
    return d


def business_days_after(start: date, end: date, holidays: set[date]) -> int:
    """How many business days lie in (start, end]."""
    d, counted = start, 0
    while d < end:
        d += timedelta(days=1)
        if is_business_day(d, holidays):
            counted += 1
    return counted


def parse_date(text: str) -> date | None:
    """Parse '17 October 2026' / '2026-10-17' / '5 October' (year defaults 2026)."""
    import re
    t = text
    m = re.search(r"(20\d{2})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    month_names = {name.lower(): i for i, name in enumerate(MONTHS_EN) if name}
    # iterate ALL matches - the first digit in the text may be part of a
    # product name ('Fit 3 Pro ... delivered on 20 July')
    for m in re.finditer(r"(\d{1,2})\s+([A-Za-z]+)\s*(20\d{2})?", t):
        if m.group(2).lower() in month_names:
            return date(int(m.group(3) or 2026), month_names[m.group(2).lower()],
                        int(m.group(1)))
    for m in re.finditer(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(20\d{2})?", t):
        if m.group(1).lower() in month_names:
            return date(int(m.group(3) or 2026), month_names[m.group(1).lower()],
                        int(m.group(2)))
    return None


def fmt_en(d: date) -> str:
    return f"{d.day} {MONTHS_EN[d.month]} {d.year}"


def fmt_hi(d: date) -> str:
    # Hindi month name with ASCII digits - the form the dataset's own
    # reference answers use ('27 अक्टूबर 2026')
    return f"{d.day} {MONTHS_HI[d.month]} {d.year}"


def fmt_spoken(d: date) -> str:
    """Voice format per STY-3: 'the 24th of October 2026' (year always included)."""
    day = d.day
    suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"the {day}{suffix} of {MONTHS_EN[d.month]} {d.year}"


def spoken_order_id(order_id: str) -> str:
    """Order IDs read in groups of four digits (STY-3)."""
    return " ".join(order_id[i:i + 4] for i in range(0, len(order_id), 4))
