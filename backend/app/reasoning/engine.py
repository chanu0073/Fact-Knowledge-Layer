"""Phase 8 — L3 decision fusion.

``decide_pair`` runs L1 (deterministic arithmetic) first. Pairs L1 cannot settle
(strength == WEAK but comparable) are offered to an L2 LLM judge; the L2 verdict
is trusted only when it is confident (>= 0.6), otherwise the honest L1 verdict
stands. Deterministic L1 strong/moderate verdicts always win — no LLM round-trip
wasted, and no semantic shortcut can override arithmetic ground truth.

Pairs that are genuinely unrelated (not comparable) produce no relationship at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Evidence, Fact
from app.reasoning import l1

L2_CONFIDENCE_THRESHOLD = 0.6


@dataclass
class Decision:
    label: str
    confidence: float
    reasons: list[str] = field(default_factory=list)
    llm_reasoning: str = ""
    l2_used: bool = False
    is_synthetic: bool = False
    periods_overlap: bool | None = None
    l1_label: str = ""
    l1_strength: str = ""


async def _evidence_snippets(session: AsyncSession, fact: Fact, limit: int = 3) -> list[str]:
    if not fact.evidence_ids:
        return []
    res = await session.execute(
        select(Evidence).where(Evidence.id.in_(fact.evidence_ids)).limit(limit)
    )
    return [e.content[:200] for e in res.scalars().all()]


def _l2_context(fact: Fact, snippets: list[str]) -> dict:
    return {
        "entity": fact.entity,
        "metric": fact.metric,
        "definition": fact.definition,
        "raw_value": fact.raw_value,
        "numeric_value": fact.numeric_value,
        "unit": fact.unit,
        "currency": fact.currency,
        "value_type": fact.value_type,
        "period_raw": fact.period_raw,
        "fiscal_year_label": fact.fiscal_year_label,
        "observation_type": fact.observation_type,
        "scope": fact.scope,
        "geography": fact.geography,
        "grounding": (fact.qualifiers or {}).get("grounding", ""),
        "evidence": snippets,
    }


async def decide_pair(
    session: AsyncSession,
    fact_a: Fact,
    fact_b: Fact,
    reasoner=None,
    *,
    allow_l2: bool = True,
) -> Decision | None:
    """Full L1 → (L2) → L3 decision for one ordered pair. None when unrelated."""
    if fact_a.id == fact_b.id:
        return None

    verdict = l1.reason_pair(fact_a, fact_b)
    if not verdict.comparable:
        return None

    decision = Decision(
        label=verdict.label,
        confidence=verdict.confidence,
        reasons=list(verdict.reasons),
        is_synthetic=bool(
            (fact_a.qualifiers or {}).get("is_synthetic")
            or (fact_b.qualifiers or {}).get("is_synthetic")
        ),
        periods_overlap=verdict.periods_overlap,
        l1_label=verdict.label,
        l1_strength=verdict.strength,
    )

    if verdict.strength == l1.WEAK and reasoner is not None and allow_l2:
        ctx_a = _l2_context(fact_a, await _evidence_snippets(session, fact_a))
        ctx_b = _l2_context(fact_b, await _evidence_snippets(session, fact_b))
        conclusion = await reasoner.reason(ctx_a, ctx_b)
        decision.l2_used = True
        if conclusion.confidence >= L2_CONFIDENCE_THRESHOLD:
            label = conclusion.label if conclusion.label in l1.RELATIONSHIP_TYPES else l1.UNCERTAIN
            decision.label = label
            decision.confidence = conclusion.confidence
            decision.reasons.append(
                f"L2 ({reasoner.name}): {conclusion.rationale}".strip()
            )
            decision.llm_reasoning = conclusion.rationale

    return decision