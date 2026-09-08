"""Phase 8 — L1 deterministic relationship reasoning.

Decides a pair of candidate facts using ONLY their normalised fields
(Phase 5): canonical money on a shared scale, percent/ratio values, and
period windows. Embedding/retrieval scores are never consulted — if they were
used for verdicts they could shortcut the arithmetic grounding rule.

Every verdict is reproducible and carries human-readable ``reasons``, so a
wrong answer is diagnosable. Verdicts L1 cannot settle get ``WEAK`` strength
and are handed to L2 (an LLM judge) by ``engine.decide_pair``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.models import Fact
from app.normalize import canonical_money
from app.retrieval import metric_tokens

CORROBORATES = "CORROBORATES"
LIKELY_CONTRADICTION = "LIKELY_CONTRADICTION"
APPARENT_CONTRADICTION_RESOLVED = "APPARENT_CONTRADICTION_RESOLVED"
UNCERTAIN = "UNCERTAIN"

RELATIONSHIP_TYPES = (
    CORROBORATES,
    LIKELY_CONTRADICTION,
    APPARENT_CONTRADICTION_RESOLVED,
    UNCERTAIN,
)

STRONG = "strong"
MODERATE = "moderate"
WEAK = "weak"

# Cross-document rounding tolerance: two independently-rounded statements of
# the same figure can differ by a few % (e.g. 8,142 Cr = 81,420 Mn vs
# 81,415.38 Mn is 0.006%). 3% is a defensible ceiling for "same number".
TOLERANCE = 0.03
EPS = 1e-9

OBS_ACTUAL = {"actual", "historical"}
OBS_NONACTUAL = {"estimate", "forecast", "projection", "guidance"}


@dataclass
class L1Verdict:
    label: str
    confidence: float
    strength: str
    reasons: list[str] = field(default_factory=list)
    comparable: bool = True
    periods_overlap: bool | None = None


def pct_diff(a: float, b: float) -> float:
    return abs(a - b) / max(abs(a), abs(b), EPS)


def _is_actual(fact: Fact) -> bool:
    return (fact.observation_type or "").lower() in OBS_ACTUAL


def _is_nonactual(fact: Fact) -> bool:
    return (fact.observation_type or "").lower() in OBS_NONACTUAL


def _periods_overlap(a: Fact, b: Fact) -> bool | None:
    """True/False when both windows are known; label-equality fallback; else None."""
    if a.period_start and a.period_end and b.period_start and b.period_end:
        return bool(a.period_start <= b.period_end and b.period_start <= a.period_end)
    if a.fiscal_year_label and b.fiscal_year_label:
        return a.fiscal_year_label == b.fiscal_year_label
    return None


def _common_scale(a: Fact, b: Fact, reasons: list[str]) -> tuple[float, float, str] | None:
    """(val_a, val_b, scale_label) for numerically comparable value types, else None."""
    a_is_pct = a.value_type in ("percent", "ratio")
    b_is_pct = b.value_type in ("percent", "ratio")
    if a_is_pct != b_is_pct:
        reasons.append(
            f"value types differ ({a.value_type or 'unknown'} vs {b.value_type or 'unknown'}); not numerically comparable"
        )
        return None
    if a_is_pct and b_is_pct:
        return a.numeric_value, b.numeric_value, "unscaled % values"

    ma, mb = canonical_money(a), canonical_money(b)
    if ma is None or mb is None:
        reasons.append("both sides must be money-typed values on a common scale")
        return None
    (am, cur_a), (bm, cur_b) = ma, mb
    if cur_a and cur_b and cur_a != cur_b:
        reasons.append(f"currencies differ ({cur_a} vs {cur_b}); no FX applied")
        return None
    return am, bm, "millions (normalised money)"


def reason_pair(a: Fact, b: Fact) -> L1Verdict:
    """Deterministic arithmetic verdict for the pair (a, b)."""
    reasons: list[str] = []

    mt_a, mt_b = metric_tokens(a.metric), metric_tokens(b.metric)
    ent_a, ent_b = metric_tokens(a.entity), metric_tokens(b.entity)
    metric_ok = (not mt_a or not mt_b) or bool(mt_a & mt_b)
    entity_ok = (not ent_a or not ent_b) or bool(ent_a & ent_b)
    if not (metric_ok and entity_ok):
        reasons.append(f"metrics/entities do not align ({a.entity or '?'} {a.metric or '?'} vs {b.entity or '?'} {b.metric or '?'})")
        return L1Verdict(UNCERTAIN, 0.3, WEAK, reasons, comparable=False)

    if a.numeric_value is None or b.numeric_value is None:
        reasons.append("one or both facts lack a numeric value")
        return L1Verdict(UNCERTAIN, 0.3, WEAK, reasons)

    scale = _common_scale(a, b, reasons)
    if scale is None:
        return L1Verdict(UNCERTAIN, 0.35, WEAK, reasons)

    val_a, val_b, scale_label = scale
    diff = pct_diff(val_a, val_b)
    overlap = _periods_overlap(a, b)
    both_actual = _is_actual(a) and _is_actual(b)
    nonactual_mix = _is_nonactual(a) or _is_nonactual(b)
    unit_note = f"{scale_label} (Δ{diff * 100:.2f}%)"

    if diff <= TOLERANCE:
        reasons.append(f"values within tolerance in {unit_note}; {a.raw_value!r} ≈ {b.raw_value!r}")
        if overlap is True:
            reasons.append("periods overlap")
            return L1Verdict(CORROBORATES, 0.92, STRONG, reasons, periods_overlap=True)
        reasons.append("period windows differ or are unresolved — same figure reported across windows")
        return L1Verdict(CORROBORATES, 0.7, MODERATE, reasons, periods_overlap=overlap)

    # Values differ beyond tolerance.
    if overlap is False:
        reasons.append(f"values differ in {unit_note} but periods are disjoint — difference expected, not a contradiction")
        return L1Verdict(APPARENT_CONTRADICTION_RESOLVED, 0.9, STRONG, reasons, periods_overlap=False)

    if overlap is None:
        if both_actual:
            reasons.append(f"both stated as actual with values differing in {unit_note}; period overlap unknown")
            return L1Verdict(LIKELY_CONTRADICTION, 0.7, MODERATE, reasons, periods_overlap=None)
        reasons.append(f"values differ in {unit_note}; period overlap unknown and observation types unclear")
        return L1Verdict(UNCERTAIN, 0.45, WEAK, reasons, periods_overlap=None)

    if both_actual:
        reasons.append(f"both actual observations in the same period, values differ in {unit_note} — inconsistency")
        return L1Verdict(LIKELY_CONTRADICTION, 0.9, STRONG, reasons, periods_overlap=True)

    if nonactual_mix:
        reasons.append(f"values differ in {unit_note} but one side is estimate/guidance/projection vs actual — variance is expected")
        return L1Verdict(APPARENT_CONTRADICTION_RESOLVED, 0.45, WEAK, reasons, periods_overlap=True)

    reasons.append(f"values differ in {unit_note} in an overlapping period with unclear observation types")
    return L1Verdict(UNCERTAIN, 0.55, MODERATE, reasons, periods_overlap=True)