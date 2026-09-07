"""Generic, deterministic parsers shared by the sample extractor (and later the normaliser).

Phase 4 uses these to turn raw text into (number, unit, currency, period) hints.
Phase 5 will formalise them into the canonical value/unit/period model.
"""
from __future__ import annotations

import re

NUM_PAT = re.compile(
    r"([-+]?\s?[\d,]{1,15}(?:\.\d+)?)\s*(%|percent|₹|Rs\.?|INR|USD|US\$|\$|Cr\.?|Mn|mn|crore|million|M\b|billion|Bn|trillion|thousand|lakh)?"
)
FY_RE = re.compile(r"\bFY\.?\s*(20\d\d|\d\d)\b", re.IGNORECASE)
YEAR_RANGE_RE = re.compile(r"\b(20\d\d)\s*[-–]\s*(20\d\d|FY\s*20\d\d|FY\d\d)\b")
SINGLE_YEAR_RE = re.compile(r"\b20\d\d\b")
QUARTER_RE = re.compile(r"\b(Q[1-4]|H1|H2|9M|6M|3M)\b", re.IGNORECASE)
AS_AT_RE = re.compile(r"\b(as of|as at)\s+(.*\b20\d\d\b)", re.IGNORECASE)
PERCENT_WORDS = ("percent", "%")
MONIES = {
    "crore": 1e7, "cr": 1e7, "cr.": 1e7,
    "lakh": 1e5,
    "million": 1e6, "mn": 1e6, "mn.": 1e6,
    "billion": 1e9, "bn": 1e9, "bn.": 1e9,
    "thousand": 1e3,
}

COMMON_ENTITY_TOKENS = {
    "annual", "report", "limited", "ltd", "india", "indian", "quarter", "result",
    "fy", "financial", "year", "ended", "for", "and", "the", "of", "on", "with",
    "consolidated", "standalone", "audited", "board", "bse", "nse", "investor",
}


def clean_number(num: str) -> float:
    r"""'−' unicode minus, commas, optional sign → float. Pattern: -?[\d,]+(\.\d+)?"""
    s = num.replace(",", "").replace("−", "-").replace(" ", "").strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def first_money(text: str) -> tuple[list[str] | None, str]:
    """Return ([number, suffix], matched_text) of the first monetary/percent token."""
    for m in NUM_PAT.finditer(text):
        token = m.group(1)
        suffix = (m.group(2) or "").strip()
        if token:
            return [token, suffix], m.group(0)
    return None, ""


def best_money(text: str) -> tuple[list[str] | None, str]:
    """Return ([number, suffix], matched_text) favouring the largest magnitude number.

    Purely heuristic. 'March 31, 2024, revenue was Rs 81,415.38 million' —
    first_money would catch '31', but the meaningful figure is 81,415.38.
    """
    best: tuple[list[str], str] | None = None
    best_abs = -1.0
    for m in NUM_PAT.finditer(text):
        token, suffix = m.group(1), (m.group(2) or "").strip()
        if not token:
            continue
        magnitude = abs(clean_number(token))
        if magnitude > best_abs:
            best = ([token, suffix], m.group(0))
            best_abs = magnitude
    return best if best else (None, "")


def has_number(text: str) -> bool:
    return bool(re.search(r"\d", text))


def detect_unit_and_currency(text: str) -> tuple[str, str]:
    """Best-effort (unit, currency) inference from raw context."""
    low = text.lower()
    unit = ""
    currency = ""

    if "₹" in text or "rs." in low or " inr" in (" " + low) or "indian rupee" in low:
        currency = "INR"
    elif "$" in text or " usd" in (" " + low) or "us dollar" in low:
        currency = "USD"
    elif "€" in text:
        currency = "EUR"

    scale = None
    for word, mult in MONIES.items():
        # word is a suffix like crore; avoid matching "compilation"
        if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
            scale = word
            break
    if scale in ("crore", "cr", "lakh", "million", "mn", "billion", "bn", "thousand"):
        unit = f"{currency or ''} {scale}".strip()
    if "%" in text or " percent" in low:
        unit = "percent"

    return unit, currency


def infer_period(text: str) -> dict:
    """Very cheap period inference. Formalised in Phase 5."""
    info = {"period_raw": "", "period_type": "unknown", "fiscal_year_label": ""}

    m = AS_AT_RE.search(text)
    if m:
        info["period_raw"] = m.group(0).strip()
        info["period_type"] = "date"
        return info

    m = QUARTER_RE.search(text)
    has_q = m.group(1).upper() if m else ""

    m = FY_RE.search(text)
    if m:
        yr = m.group(1)
        label = f"FY{int(yr):04d}" if len(yr) == 2 else f"FY{yr}"
        info["period_raw"] = m.group(0).strip()
        info["fiscal_year_label"] = label
        info["period_type"] = "quarter" if has_q else "fiscal_year"
        return info

    m = YEAR_RANGE_RE.search(text)
    if m:
        end = m.group(2)
        end_yr = re.search(r"(20\d\d)", end).group(1)
        info["period_raw"] = m.group(0).strip()
        info["fiscal_year_label"] = f"FY{end_yr}"
        info["period_type"] = "quarter" if has_q else "fiscal_year"
        return info

    m = SINGLE_YEAR_RE.search(text)
    if m:
        info["period_raw"] = m.group(0)
        info["fiscal_year_label"] = f"FY{m.group(0)}"
        info["period_type"] = "fiscal_year"
        return info

    return info


def infer_observation_type(text: str) -> str:
    low = text.lower()
    mapping = (
        ("guidance", "guidance"),
        ("projection", "projection"),
        ("forecast", "forecast"),
        ("estimate", "estimate"),
        ("actual", "actual"),
        ("historical", "historical"),
    )
    for key, label in mapping:
        if key in low:
            return label
    return "unknown"


def strip_noise_prefix(text: str) -> str:
    """Remove page numbers / bullet numbers and surrounding whitespace."""
    t = re.sub(r"^\s*(?:[-•·▪·\d.]+)\s*", "", text)
    return t.strip()


def infer_entity(blocks_texts: list[str]) -> str:
    """Most frequent capitalized 2-gram across evidence (generic, no hardcoding)."""
    from collections import Counter

    grams: Counter = Counter()
    for t in blocks_texts[:60]:
        words = re.findall(r"([A-Z][A-Za-z&'.-]+[ ]?[A-Z][A-Za-z&'.-]+|[A-Z][A-Za-z&'.-]+)", t)
        for w in words:
            bigram_parts = re.findall(r"[A-Z][A-Za-z&'.-]+", w)
            if len(bigram_parts) == 2 and all(p.lower() not in COMMON_ENTITY_TOKENS for p in bigram_parts):
                grams[bigram_parts[0] + " " + bigram_parts[1]] += 1
    if grams:
        return grams.most_common(1)[0][0]
    return "unknown"