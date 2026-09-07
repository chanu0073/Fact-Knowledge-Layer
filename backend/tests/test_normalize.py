"""Phase 5 unit tests: value/unit/period canonicalisation."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.normalize import (
    canonical_money,
    parse_numeric_value,
    parse_period,
    to_millions,
)


def _t(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


class TestParseNumericValue:
    @pytest.mark.parametrize("raw,expected", [
        ("8,142", 8142.0),
        ("81,415.38", 81415.38),
        ("₹8,142 Cr", 8142.0),
        ("(4,516)", -4516.0),
        ("-1,234", -1234.0),
        ("78.9%", 78.9),
        ("1,519", 1519.0),
        ("2,076.41", 2076.41),
        ("N/A", None),
        ("", None),
    ])
    def test_parse(self, raw, expected):
        assert parse_numeric_value(raw) == expected


class TestScaleHelpers:
    def test_money_scale(self):
        assert to_millions(8142, "INR crore") == pytest.approx(81420.0)
        assert to_millions(81415.38, "INR million") == pytest.approx(81415.38)
        assert to_millions(2076, "INR lakh") == pytest.approx(207.6)
        assert to_millions(1.3, "US dollar trillion") == pytest.approx(1_300_000.0)

    def test_canonical_money(self):
        class F:
            numeric_value = 8142.0
            unit = "INR crore"
            currency = "INR"
            value_type = "absolute"
        amount, currency = canonical_money(F())
        assert amount == pytest.approx(81420.0)
        assert currency == "INR"


class TestParsePeriod:
    def test_fy(self):
        r = parse_period("FY2024")
        assert r["period_type"] == "fiscal_year"
        assert r["fiscal_year_label"] == "FY2024"
        assert r["period_start"] == _t(2023, 4, 1)
        assert r["period_end"] == _t(2024, 3, 31)

    def test_fy_two_digit(self):
        r = parse_period("FY24")
        assert r["fiscal_year_label"] == "FY2024"
        assert r["period_start"] == _t(2023, 4, 1)

    def test_quarter(self):
        r = parse_period("Q1 FY2025")
        assert r["period_type"] == "quarter"
        assert r["fiscal_year_label"] == "FY2025"
        assert r["period_start"] == _t(2024, 4, 1)
        assert r["period_end"] == _t(2024, 6, 30)

    def test_quarter_postfix(self):
        r = parse_period("2024 Q3")
        assert r["fiscal_year_label"] == "FY2024"
        assert r["period_start"] == _t(2023, 10, 1)
        assert r["period_end"] == _t(2023, 12, 31)

    def test_h1(self):
        r = parse_period("H1 FY2025")
        assert r["period_type"] == "range"
        assert r["period_start"] == _t(2024, 4, 1)
        assert r["period_end"] == _t(2024, 9, 30)

    def test_9m(self):
        r = parse_period("9M FY2021")
        assert r["period_start"] == _t(2020, 4, 1)
        assert r["period_end"] == _t(2020, 12, 31)

    def test_fy_range(self):
        r = parse_period("2024-25")
        assert r["fiscal_year_label"] == "FY2025"
        assert r["period_start"] == _t(2024, 4, 1)
        assert r["period_end"] == _t(2025, 3, 31)

    def test_month_range(self):
        r = parse_period("April 2023 to March 2024")
        assert r["period_type"] == "range"
        assert r["period_start"] == _t(2023, 4, 1)
        assert r["period_end"] == _t(2024, 3, 31)

    def test_explicit_date(self):
        r = parse_period("As at 31 March 2024")
        assert r["period_type"] == "date"
        assert r["period_start"] == r["period_end"] == _t(2024, 3, 31)

    def test_explicit_date_us(self):
        r = parse_period("ended March 31, 2025")
        assert r["period_type"] == "date"
        assert r["period_start"] == _t(2025, 3, 31)

    def test_month(self):
        r = parse_period("March 2024")
        assert r["period_type"] == "month"
        assert r["period_start"] == _t(2024, 3, 1)
        assert r["period_end"] == _t(2024, 3, 31)

    def test_bare_year_is_calendar(self):
        r = parse_period("2024")
        assert r["period_type"] == "date"
        assert r["period_start"] == _t(2024, 1, 1)
        assert r["period_end"] == _t(2024, 12, 31)
        assert r["fiscal_year_label"] == ""

    def test_garbage(self):
        r = parse_period("n/a")
        assert r["period_type"] == "unknown"
        assert r["period_start"] is None

    def test_empty(self):
        assert parse_period("")["period_type"] == "unknown"
        assert parse_period(None)["period_type"] == "unknown"