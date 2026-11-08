"""Date parsing & calendar conversion for Ethiopia and Gregorian timelines.

Supports:
  1. Zero-dependency, mathematically exact Ethiopian Calendar (EC) -> Gregorian (GC) conversion.
  2. Amharic month name recognition (e.g. መስከረም, ጥቅምት, ህዳር, ታህሳስ...).
  3. Transliterated Ethiopian months (Meskerem, Tikimt, Hidar...).
  4. Standard Gregorian textual and numeric dates (ISO, DD/MM/YYYY, English month names).
  5. Relative deadline expressions ("within 10 days", "in 5 days", "በ 10 ቀናት ውስጥ").
"""
from __future__ import annotations

import datetime
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Ethiopian Calendar Math
# ---------------------------------------------------------------------------
# The Ethiopian calendar consists of 12 months of 30 days each, plus 5 or 6
# epagomenal days (Pagume).
# The JDN epoch for Meskerem 1, 1 EC is Julian Day Number 1,724,221.
# Python's datetime.date.toordinal(date(1, 1, 1)) == 1, which corresponds to JDN 1,721,426.
# Therefore, ordinal = jdn - 1,721,425.

ETHIOPIAN_EPOCH_JDN = 1724221
GREGORIAN_EPOCH_OFFSET = 1721425


def ethiopian_to_gregorian(year: int, month: int, day: int) -> datetime.date:
    """Convert an Ethiopian Calendar date (year, month 1..13, day 1..30) to Gregorian date."""
    if not (1 <= month <= 13):
        raise ValueError(f"Invalid Ethiopian month: {month} (must be 1..13)")
    max_days = 6 if month == 13 else 30
    if not (1 <= day <= max_days):
        raise ValueError(f"Invalid Ethiopian day {day} for month {month}")

    jdn = (
        ETHIOPIAN_EPOCH_JDN
        + 365 * (year - 1)
        + (year // 4)
        + 30 * (month - 1)
        + (day - 1)
    )
    ordinal = jdn - GREGORIAN_EPOCH_OFFSET
    return datetime.date.fromordinal(ordinal)


def gregorian_to_ethiopian(year: int, month: int, day: int) -> tuple[int, int, int]:
    """Convert a Gregorian date to Ethiopian Calendar (year, month, day)."""
    target = datetime.date(year, month, day)
    jdn = target.toordinal() + GREGORIAN_EPOCH_OFFSET
    r = (jdn - ETHIOPIAN_EPOCH_JDN) % 1461
    n = (r % 365) + 365 * (r // 1460)
    eyear = 4 * ((jdn - ETHIOPIAN_EPOCH_JDN) // 1461) + (r // 365) - (r // 1460) + 1
    emonth = (n // 30) + 1
    eday = (n % 30) + 1
    return eyear, emonth, eday


# ---------------------------------------------------------------------------
# Month Dictionaries
# ---------------------------------------------------------------------------
ETHIOPIAN_MONTHS: dict[str, int] = {
    # Amharic script
    "መስከረም": 1,
    "ጥቅምት": 2,
    "ህዳር": 3,
    "ኅዳር": 3,
    "ታህሳስ": 4,
    "ታኅሣሥ": 4,
    "ታህሣሥ": 4,
    "ጥር": 5,
    "የካቲት": 6,
    "መጋቢት": 7,
    "ሚያዝያ": 8,
    "ሚያዚያ": 8,
    "ግንቦት": 9,
    "ሰኔ": 10,
    "ሐምሌ": 11,
    "ሀምሌ": 11,
    "ነሐሴ": 12,
    "ነሀሴ": 12,
    "ጳጉሜ": 13,
    "ጳጉሜን": 13,
    # Transliterated
    "meskerem": 1,
    "maskaram": 1,
    "tikimt": 2,
    "teqemt": 2,
    "tiqimt": 2,
    "hidar": 3,
    "hedar": 3,
    "tahsas": 4,
    "tahisas": 4,
    "tir": 5,
    "ter": 5,
    "yakatit": 6,
    "yekatit": 6,
    "megabit": 7,
    "maggabit": 7,
    "miyazya": 8,
    "miazia": 8,
    "ginbot": 9,
    "genbot": 9,
    "sene": 10,
    "hamle": 11,
    "nehase": 12,
    "nahase": 12,
    "pagume": 13,
    "pagumen": 13,
}

GREGORIAN_MONTHS: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Regex pre-compilations
_ETH_MONTHS_PATTERN = "|".join(re.escape(m) for m in ETHIOPIAN_MONTHS.keys())
_GREG_MONTHS_PATTERN = "|".join(re.escape(m) for m in GREGORIAN_MONTHS.keys())

# Ethiopian textual: e.g. "ጥቅምት 30, 2017" or "ጥቅምት 30 2017 ዓ.ም" or "30 ጥቅምት 2017"
_RE_ETH_TEXTUAL_1 = re.compile(
    rf"(?P<month>{_ETH_MONTHS_PATTERN})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th|ቀን)?(?:[\s,]+(?P<year>201\d|202\d))?",
    re.IGNORECASE,
)
_RE_ETH_TEXTUAL_2 = re.compile(
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th|ቀን)?\s+(?P<month>{_ETH_MONTHS_PATTERN})(?:[\s,]+(?P<year>201\d|202\d))?",
    re.IGNORECASE,
)

# Explicit EC marker: "ዓ.ም", "ዓ/ም", "E.C."
_RE_EC_MARKER = re.compile(r"(?:ዓ\.?\s*ም|ዓ\s*/\s*ም|e\.?c\.?)", re.IGNORECASE)

# Gregorian textual: "November 18, 2026" or "18th Nov 2026"
_RE_GREG_TEXTUAL_1 = re.compile(
    rf"(?P<month>{_GREG_MONTHS_PATTERN})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?(?:[\s,]+(?P<year>202\d|203\d))?",
    re.IGNORECASE,
)
_RE_GREG_TEXTUAL_2 = re.compile(
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{_GREG_MONTHS_PATTERN})(?:[\s,]+(?P<year>202\d|203\d))?",
    re.IGNORECASE,
)

# ISO date format: YYYY-MM-DD
_RE_ISO = re.compile(r"\b(?P<year>202\d|203\d)[-/](?P<month>0?[1-9]|1[0-2])[-/](?P<day>0?[1-9]|[12]\d|3[01])\b")

# Numeric slashed/dashed: DD/MM/YYYY or DD-MM-YYYY
_RE_NUMERIC_DMY = re.compile(
    r"\b(?P<day>0?[1-9]|[12]\d|3[01])[-/.](?P<month>0?[1-9]|1[0-2])[-/.](?P<year>201\d|202\d|203\d)\b"
)

# Relative deadlines: "within 10 days", "in 5 days", "በ 7 ቀናት ውስጥ"
_RE_RELATIVE_EN = re.compile(r"(?:within|in|left)\s+(\d{1,2})\s+(?:working\s+|calendar\s+)?days?", re.IGNORECASE)
_RE_RELATIVE_AM = re.compile(r"በ\s*(\d{1,2})\s*(?:ተከታታይ\s+|የስራ\s+)?ቀናት?\s*ውስጥ", re.IGNORECASE)


def parse_date(
    text: str | None,
    reference_date: datetime.date | None = None,
) -> Optional[datetime.date]:
    """Parse a date string in Ethiopian or Gregorian format into a Gregorian datetime.date.

    If year is omitted, infers based on the reference_date (defaults to today).
    """
    if not text or not text.strip():
        return None

    raw = text.strip()
    ref = reference_date or datetime.date.today()
    ref_eyear, _, _ = gregorian_to_ethiopian(ref.year, ref.month, ref.day)

    # 1. Check relative deadline: "within 10 days" / "በ 10 ቀናት ውስጥ"
    m_rel = _RE_RELATIVE_EN.search(raw) or _RE_RELATIVE_AM.search(raw)
    if m_rel:
        try:
            days = int(m_rel.group(1))
            if 0 < days <= 90:
                return ref + datetime.timedelta(days=days)
        except ValueError:
            pass

    # 2. Check Ethiopian month textual match: "ጥቅምት 30, 2017" or "30 ጥቅምት"
    m_eth = _RE_ETH_TEXTUAL_1.search(raw) or _RE_ETH_TEXTUAL_2.search(raw)
    if m_eth:
        m_str = m_eth.group("month").lower()
        emonth = ETHIOPIAN_MONTHS.get(m_str)
        if emonth:
            try:
                eday = int(m_eth.group("day"))
                eyear_raw = m_eth.group("year")
                eyear = int(eyear_raw) if eyear_raw else ref_eyear
                # Handle possible 2-digit Ethiopian year like '17 -> 2017
                if eyear < 100:
                    eyear += 2000
                return ethiopian_to_gregorian(eyear, emonth, min(eday, 30 if emonth < 13 else 6))
            except Exception:
                pass

    # 3. Check ISO format (YYYY-MM-DD)
    m_iso = _RE_ISO.search(raw)
    if m_iso:
        try:
            gyear = int(m_iso.group("year"))
            gmonth = int(m_iso.group("month"))
            gday = int(m_iso.group("day"))
            # If explicit EC marker present, convert from EC
            if _RE_EC_MARKER.search(raw) or (2015 <= gyear <= 2020 and "ዓ" in raw):
                return ethiopian_to_gregorian(gyear, gmonth, gday)
            return datetime.date(gyear, gmonth, gday)
        except ValueError:
            pass

    # 4. Check Gregorian textual: "November 18, 2026", "18th Nov 2026"
    m_greg = _RE_GREG_TEXTUAL_1.search(raw) or _RE_GREG_TEXTUAL_2.search(raw)
    if m_greg:
        m_str = m_greg.group("month").lower()
        gmonth = GREGORIAN_MONTHS.get(m_str)
        if gmonth:
            try:
                gday = int(m_greg.group("day"))
                gyear_raw = m_greg.group("year")
                gyear = int(gyear_raw) if gyear_raw else ref.year
                return datetime.date(gyear, gmonth, min(gday, 31))
            except ValueError:
                pass

    # 5. Check numeric DD/MM/YYYY
    m_num = _RE_NUMERIC_DMY.search(raw)
    if m_num:
        try:
            day = int(m_num.group("day"))
            month = int(m_num.group("month"))
            year = int(m_num.group("year"))
            # If explicit Ethiopian calendar marker or year matches EC range (2016..2020) with EC marker
            if _RE_EC_MARKER.search(raw) or (2015 <= year <= 2020 and ("ዓ" in raw or "ec" in raw.lower())):
                return ethiopian_to_gregorian(year, month, min(day, 30))
            return datetime.date(year, month, day)
        except (ValueError, OverflowError):
            pass

    return None
