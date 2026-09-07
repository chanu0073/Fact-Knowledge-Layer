"""Canonical value / unit / period normalisation (Phase 5).

Deterministic, unit-tested, provider-independent. Two jobs:

1. Turn the extractor's `raw_value`/`unit`/`period_raw` into canonical columns:
   ``numeric_value`` (clean float as-written), ``unit``/``currency``,
   ``period_start``/``period_end``/``period_type``/``fiscal_year_label``.
2. Provide scale-aware helpers (``to_millions`` etc.) that Phase 8 (reasoning)
   uses to compare numbers across units — e.g. 8,142 Cr vs 81,415.38 Mn.

Fiscal-year convention is configurable (``FISCAL_START_MONTH``, default 4 → India
FY runs Apr–Mar). A bare year like "2024" is treated as a calendar year.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone

from app.config import settings

FY_START_MONTH: int = settings.fiscal_year_start_month

MONEY_SCALES: dict[str, float] = {
    "thousand": 1e3,
    "lakh": 1e5,
    "million": 1e6, "mn": 1e6,
    "crore": 1e7, "cr": 1e7,
    "billion": 1e9, "bn": 1e9,
    "trillion": 1e12,
}

NUM_TOKEN = re.compile(r"([-+]?\s?\(?[\d,]{1,15}(?:\.\d+)?\)?)")

# --- numeric_value ----------------------------------------------------------

def parse_numeric_value(raw: str) -> float | None:
    """Clean scalar as written in the document, e.g. "8,142 Cr" → 8142.0."""
    if not raw:
        return None
    m = NUM_TOKEN.search(_normalize_signs(raw))
    if not m:
        return None
    token = m.group(1).strip()
    is_paren_neg = "(" in token and ")" in token
    token = token.replace("−", "-").replace("(", "").replace(")", "").replace(",", "").replace(" ", "").lstrip("+")
    try:
        val = float(token)
    except ValueError:
        return None
    return -val if is_paren_neg else val


def _normalize_signs(text: str) -> str:
    return text.replace("−", "-")


def percent_of(raw: str) -> bool:
    return bool(re.search(r"%|percent", raw, re.IGNORECASE))


# --- unit / currency --------------------------------------------------------

def money_scale(unit: str) -> float:
    """Scale factor of a unit string relative to 1, e.g. 'INR crore' → 1e7."""
    if not unit:
        return 1.0
    low = unit.lower()
    for word, mult in MONEY_SCALES.items():
        if re.search(rf"\b{re.escape(word)}\b", low):
            return mult
    return 1.0


def is_money_unit(unit: str) -> bool:
    return money_scale(unit) > 1.0 or bool(re.search(r"\b(unit|usd|inr|eur|rupee[s]?|₹)\b", unit, re.IGNORECASE))


def to_millions(value: float, unit: str) -> float:
    """Scale ``value`` (in its own unit) to a canonical 'millions' amount."""
    return value * money_scale(unit) / 1e6


def canonical_money(fact) -> tuple[float, str | None] | None:
    """(amount_in_millions, currency) for absolute money facts; None if non-money."""
    if fact.numeric_value is None:
        return None
    if fact.value_type in ("percent", "ratio"):
        return fact.numeric_value, None
    if money_scale(fact.unit or "") <= 1.0 and not is_money_unit(fact.unit or ""):
        return None
    return to_millions(fact.numeric_value, fact.unit or ""), fact.currency or None


# --- period parsing ---------------------------------------------------------

def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=timezone.utc)


def _last_day(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _fy_window(label_year: int) -> tuple[datetime, datetime]:
    """Fiscal year window ending in `label_year` (e.g. FY2024 → Apr23–Mar24)."""
    start_y = label_year - 1
    end_y = label_year
    # With FY_START_MONTH S: year runs S(y-1) .. S-1(y).
    start = _dt(start_y, FY_START_MONTH, 1)
    end_month = FY_START_MONTH - 1 or 12
    end_year = end_y if FY_START_MONTH > 1 else end_y
    end = _dt(end_year, end_month, _last_day(end_year, end_month))
    return start, end


QTR_MONTHS = {1: 0, 2: 3, 3: 6, 4: 9}  # offset from FY start month


def _fiscal_start_end(label_year: int, offset_months: int, span_months: int | None = None):
    """Window within a fiscal year: offset (months from FY start) + optional span."""
    start_year = label_year - 1 + (FY_START_MONTH + offset_months - 1) // 12
    start_month = ((FY_START_MONTH + offset_months - 1) % 12) + 1
    start = _dt(start_year, start_month, 1)
    if span_months is None:
        return start, start
    last_month_0 = start_month - 1 + (span_months - 1)
    e_year = start_year + last_month_0 // 12
    e_month = last_month_0 % 12 + 1
    end = _dt(e_year, e_month, _last_day(e_year, e_month))
    return start, end


# Order matters: most specific patterns first. Each handler receives the match
# and returns a fully-populated period dict (or None to keep trying).
_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
_MONTHS_ABBR = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTH_INDEX = {**_MONTHS, **_MONTHS_ABBR}


def _month_index(name: str) -> int | None:
    return _MONTH_INDEX.get(name.strip(".").lower())


def _to_fy_label(year: int) -> str:
    return f"FY{year}"


def _year_val(tok) -> int:
    if isinstance(tok, int):
        return tok + 2000 if tok <= 60 else tok
    text = str(tok)
    return int(text) + (2000 if len(text) == 2 else 0)


def _base_period() -> dict:
    return {"period_start": None, "period_end": None,
            "period_type": "unknown", "fiscal_year_label": ""}


def _h_quarter(text: str) -> dict | None:
    m = re.search(r"(?:Q([1-4]))[.\s/-]*(?:FY\.?[\s.]*)?(?:20\d\d|\d\d)", text, re.IGNORECASE) or \
        re.search(r"(?:FY\.?[\s.]*)?(?:20\d\d|\d\d)[.\s/-]*Q([1-4])", text, re.IGNORECASE)
    if not m:
        return None
    q = int(m.group(1))
    yr = _year_val([int(x) for x in re.findall(r"(20\d\d|\d\d)", text)][-1])
    start, end = _fiscal_start_end(yr, QTR_MONTHS[q], 3)
    return {**_base_period(), "period_start": start, "period_end": end,
            "period_type": "quarter", "fiscal_year_label": _to_fy_label(yr)}


def _h_half(text: str) -> dict | None:
    m = re.search(r"\b(H1|H2|9M|6M|3M)[.\s/-]*(?:FY\.?[\s.]*)?(20\d\d|\d\d)", text, re.IGNORECASE)
    if not m:
        return None
    half = m.group(1).upper()
    yr = _year_val(int(m.group(2)))
    if half == "H2":
        start, end = _fiscal_start_end(yr, 6, 6)
        span = 6
    else:
        span = {"H1": 6, "6M": 6, "9M": 9, "3M": 3}[half]
        start, end = _fiscal_start_end(yr, 0, span)
    return {**_base_period(), "period_start": start, "period_end": end,
            "period_type": "range", "fiscal_year_label": _to_fy_label(yr)}


def _h_fy(text: str) -> dict | None:
    m = re.search(r"FY\.?[\s.]*(20\d\d|\d\d)", text, re.IGNORECASE)
    if not m:
        return None
    yr = _year_val(int(m.group(1)))
    start, end = _fy_window(yr)
    return {**_base_period(), "period_start": start, "period_end": end,
            "period_type": "fiscal_year", "fiscal_year_label": _to_fy_label(yr)}


def _h_year_range(text: str) -> dict | None:
    m = re.search(r"FY\.?[\s.]*(20\d\d)[.\s/-]+(?:FY\.?[\s.]*)?(?:20\d\d)", text, re.IGNORECASE) or \
        re.search(r"(?:^|\s)(20\d\d|\d\d)[.\s/-]+(20\d\d|\d\d)(?:\s|$)", text)
    if not m:
        return None
    first, second = _year_val(int(m.group(1))), _year_val(int(m.group(2)))
    yr = second if second > first else first
    start, end = _fy_window(yr)
    return {**_base_period(), "period_start": start, "period_end": end,
            "period_type": "fiscal_year", "fiscal_year_label": _to_fy_label(yr)}


def _h_month_range(text: str) -> dict | None:
    m = re.search(r"([A-Z][a-z]{2,})\s+(\d{4})\s*(?:to|through|[-–])\s*([A-Z][a-z]{2,})\s+(\d{4})", text)
    if not m or not _month_index(m.group(1)) or not _month_index(m.group(3)):
        return None
    y1, y2 = int(m.group(2)), int(m.group(4))
    start = _dt(y1, _month_index(m.group(1)), 1)
    end = _dt(y2, _month_index(m.group(3)), _last_day(y2, _month_index(m.group(3))))
    return {**_base_period(), "period_start": start, "period_end": end, "period_type": "range"}


def _h_iso_date(text: str) -> dict | None:
    m = re.search(r"(?:as at|as of)\s+(\d{4}-\d{1,2}-\d{1,2})", text, re.IGNORECASE)
    if not m:
        return None
    y, mo, d = map(int, m.group(1).split("-"))
    dt = _dt(y, mo, d)
    return {**_base_period(), "period_start": dt, "period_end": dt, "period_type": "date"}


def _h_explicit_date(text: str) -> dict | None:
    m = re.search(r"(?:as at|as of|ended|period ended)\s+(.+)$", text, re.IGNORECASE) or \
        re.search(r"(.+)$", text)
    frag = m.group(1).strip()
    for pat in (re.compile(r"(\d{1,2})\s+([A-Z][a-z]{2,}),?\s+(20\d\d)"),
                re.compile(r"([A-Z][a-z]{2,})\s+(\d{1,2}),?\s+(20\d\d)")):
        dm = pat.search(frag)
        if not dm:
            continue
        if pat.pattern.startswith("(\\d"):
            day, mon_name, y = int(dm.group(1)), dm.group(2), int(dm.group(3))
        else:
            mon_name, day, y = dm.group(1), int(dm.group(2)), int(dm.group(3))
        if _month_index(mon_name):
            dt = _dt(y, _month_index(mon_name), day)
            return {**_base_period(), "period_start": dt, "period_end": dt, "period_type": "date"}
    return None


def _h_month(text: str) -> dict | None:
    m = re.search(r"([A-Z][a-z]{2,})\s+(20\d\d)", text)
    if not m or not _month_index(m.group(1)):
        return None
    y, mi = int(m.group(2)), _month_index(m.group(1))
    return {**_base_period(), "period_start": _dt(y, mi, 1),
            "period_end": _dt(y, mi, _last_day(y, mi)), "period_type": "month"}


def _h_bare_year(text: str) -> dict | None:
    m = re.search(r"(?<!\d)(20\d\d)(?!\d)", text)
    if not m:
        return None
    y = int(m.group(1))
    return {**_base_period(), "period_start": _dt(y, 1, 1),
            "period_end": _dt(y, 12, 31), "period_type": "date"}


def parse_period(period_raw: str) -> dict:
    """Deterministic parse of ``period_raw`` into canonical period fields."""
    text = (period_raw or "").strip()
    if not text:
        return _base_period()
    for handler in (_h_quarter, _h_half, _h_fy, _h_year_range, _h_month_range,
                    _h_iso_date, _h_explicit_date, _h_month, _h_bare_year):
        result = handler(text)
        if result is not None:
            return result
    return _base_period()