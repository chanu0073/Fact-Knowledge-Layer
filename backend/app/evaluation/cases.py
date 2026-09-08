"""Phase 9 — the four required demo cases as data.

Single source of truth for both the registration script (live corpus) and the
regression test suite, so the harness cannot drift from the definitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.reasoning import l1


@dataclass(frozen=True)
class CaseDef:
    key: str
    kind: str  # corroboration | contradiction | resolved | failure
    source: str  # extracted | SYNTHETIC_EVALUATION_FIXTURE
    title: str
    description: str
    explanation: str
    expected_relationship: str
    # Resolution filters for the two facts (applied against Document+Fact).
    fact_a: dict = field(default_factory=dict)
    fact_b: dict = field(default_factory=dict)
    # Synthetic cases materialise their own facts instead of resolving.
    synthetic_doc: str = ""
    synthetic_facts: list = field(default_factory=list)


CASES: list[CaseDef] = [
    CaseDef(
        key="case1_corroboration",
        kind="corroboration",
        source="extracted",
        title="Delhivery FY24 revenue is the same in the annual report and the earnings deck",
        description=(
            "Annual report: Total Revenue ₹81,415.38 Mn for FY24. Earnings deck: "
            "Total Revenue ₹8,142 Cr for the same period."
        ),
        explanation=(
            "Different presentations of the same number (million vs crore). The reasoner must "
            "normalise to a common scale and corroborate, not contradict."
        ),
        expected_relationship=l1.CORROBORATES,
        fact_a={"doc": "annual-report", "metric": "Total Revenue", "entity": "Delhivery"},
        fact_b={"doc": "earnings", "metric": "Total Revenue", "entity": "Delhivery"},
    ),
    CaseDef(
        key="case2_contradiction",
        kind="contradiction",
        source="SYNTHETIC_EVALUATION_FIXTURE",
        title="Synthetic: the same revenue claimed as two different numbers for FY24",
        description=(
            "Clearly-labelled fixture stating Total Revenue ₹91,000 Mn and ₹81,415.38 Mn "
            "for the same entity/metric/period."
        ),
        explanation=(
            "A genuine, unresolved clash of two actual observations in the same period — nothing in "
            "context can reconcile them, so the verdict must be LIKELY_CONTRADICTION."
        ),
        expected_relationship=l1.LIKELY_CONTRADICTION,
        synthetic_doc="SYNTHETIC-EVALUATION-FIXTURE-contradiction.pdf",
        synthetic_facts=[
            {"entity": "Delhivery", "metric": "Total Revenue", "raw_value": "₹91,000 Mn",
             "numeric_value": 91000.0, "unit": "INR million", "currency": "INR",
             "value_type": "absolute", "period_raw": "FY2024", "fiscal_year_label": "FY2024",
             "observation_type": "actual",
             "qualifiers": {"is_synthetic": True, "grounding": "synthetic_fixture"}},
            {"entity": "Delhivery", "metric": "Total Revenue", "raw_value": "₹81,415.38 Mn",
             "numeric_value": 81415.38, "unit": "INR million", "currency": "INR",
             "value_type": "absolute", "period_raw": "FY2024", "fiscal_year_label": "FY2024",
             "observation_type": "actual",
             "qualifiers": {"is_synthetic": True, "grounding": "synthetic_fixture"}},
        ],
    ),
    CaseDef(
        key="case3_resolved",
        kind="resolved",
        source="extracted",
        title="GDP growth: FY25 actual (Economic Survey) vs FY26 projection (IMF Article IV)",
        description=(
            "India's GDP growth appears as an FY25 actual in the Economic Survey and as an FY26 "
            "projection in the IMF Article IV — same metric, different years and observation types."
        ),
        explanation=(
            "The numbers differ, so a naive comparison looks contradictory; differing periods and "
            "actual-vs-projection make the difference expected — APPARENT_CONTRADICTION_RESOLVED."
        ),
        expected_relationship=l1.APPARENT_CONTRADICTION_RESOLVED,
        fact_a={"doc": "economic-survey", "metric": "GDP growth", "entity": "India"},
        fact_b={"doc": "imf", "metric": "GDP growth", "entity": "India"},
    ),
    CaseDef(
        key="case4_failure",
        kind="failure",
        source="extracted",
        title="Known failure: prospectus multi-period table column mis-association",
        description=(
            "The prospectus 'Select Financial Information' mixes 9-month and full-year columns; "
            "extraction can attach a partial-year value to the full-year period."
        ),
        explanation=(
            "Comparing a partial-year (9M) figure against a full-year figure must not produce a "
            "confident verdict — the reasoner refuses with UNCERTAIN and explains why."
        ),
        expected_relationship=l1.UNCERTAIN,
        fact_a={"doc": "prospectus", "metric": "Total Revenue", "period_type": "fiscal_year"},
        fact_b={"doc": "prospectus", "metric": "Total Revenue", "period_type": "range"},
    ),
]

BY_KEY = {c.key: c for c in CASES}