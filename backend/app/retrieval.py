"""Phase 7 — hybrid candidate retrieval for cross-document reasoning.

Given a fact, produce ranked candidate facts from *other documents* to compare
against. Two complementary recall paths, unioned and jointly re-scored:

- **vector** (ANN via HNSW): cosine top-k over ``facts.embedding``.
- **structural** (b-tree/metadata): same metric string, or overlapping period +
  entity-token overlap — this is what catches the assignment's same-fact
  different-unit pairs even when the hash/semantic embedding is mediocre.

Final score blends both: ``hybrid = 0.55*cosine_sim + 0.45*structural_sim``.
Scores are *candidate selection only* — the relationship decision (Phase 8)
never uses a raw vector similarity as a verdict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Fact

_TOKEN_RE = re.compile(r"[a-z0-9]+")

VECTOR_WEIGHT = 0.55
STRUCTURAL_WEIGHT = 0.45


def metric_tokens(metric: str) -> set[str]:
    return set(_TOKEN_RE.findall((metric or "").lower())) - {
        "the", "of", "for", "and", "in", "to", "from", "vs", "yoy"
    }


def _token_overlap(names: list[str]) -> float:
    """Jaccard overlap of the token sets of the given name strings."""
    sets = [set(_TOKEN_RE.findall(n.lower())) for n in names]
    if not sets:
        return 0.0
    base = sets[0]
    if not base:
        return 0.0
    overlap = set.intersection(*(sets[1:] or [base]))
    union = set.union(*sets)
    return len(overlap) / len(union) if union else 0.0


def _period_overlap(a: Fact, b: Fact) -> float:
    """1.0 if windows overlap, 0.5 if either side is unresolved, else 0.0."""
    if a.period_start is None or a.period_end is None or b.period_start is None or b.period_end is None:
        return 0.5 if (a.fiscal_year_label or b.fiscal_year_label) else 0.0
    if a.period_start <= b.period_end and b.period_start <= a.period_end:
        return 1.0
    return 0.0


def structural_sim(source: Fact, cand: Fact) -> tuple[float, dict]:
    """Normalised structural similarity in [0,1] + breakdown for the UI/reasons."""
    metric_overlap = _token_overlap([source.metric, cand.metric])
    entity_overlap = _token_overlap([source.entity, cand.entity])
    period = _period_overlap(source, cand)
    same_label = 1.0 if (source.fiscal_year_label and source.fiscal_year_label == cand.fiscal_year_label) else 0.0

    s = 0.45 * metric_overlap + 0.25 * entity_overlap + 0.2 * period + 0.1 * same_label
    return min(1.0, s), {
        "metric_overlap": round(metric_overlap, 3),
        "entity_overlap": round(entity_overlap, 3),
        "period_overlap": period,
        "same_fiscal_label": same_label,
    }


@dataclass
class Candidate:
    fact: Fact
    cosine_sim: float | None
    structural: float
    breakdown: dict
    hybrid_score: float
    source: str


async def _vector_candidates(session: AsyncSession, source: Fact, k: int = 40) -> list[tuple[Fact, float]]:
    if source.embedding is None:
        return []
    stmt = (
        select(Fact, (1 - Fact.embedding.cosine_distance(source.embedding)).label("sim"))
        .where(Fact.embedding.isnot(None), Fact.document_id != source.document_id)
        .order_by(Fact.embedding.cosine_distance(source.embedding))
        .limit(k)
    )
    res = await session.execute(stmt)
    return [(row.Fact, float(row.sim)) for row in res.all()]


async def _structural_candidates(session: AsyncSession, source: Fact, limit: int = 60) -> list[Fact]:
    """Same-metric or same-entity-period facts from other documents (index-assisted)."""
    src_tokens = metric_tokens(source.metric)
    other = Fact.document_id != source.document_id

    conditions = []
    if source.metric.strip():
        conditions.append(Fact.metric.ilike(source.metric.strip()))
    if source.fiscal_year_label and src_tokens:
        conditions.append(Fact.fiscal_year_label == source.fiscal_year_label)

    if not conditions:
        return []

    stmt = select(Fact).where(other, or_(*conditions)).limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


async def retrieve_candidates(
    session: AsyncSession,
    source: Fact,
    limit: int = 20,
    vector_k: int = 40,
) -> list[Candidate]:
    """Ranked cross-document candidates for ``source`` (hybrid score)."""
    seen: dict[str, Candidate] = {}

    for fact, sim in await _vector_candidates(session, source, vector_k):
        structural, breakdown = structural_sim(source, fact)
        score = VECTOR_WEIGHT * sim + STRUCTURAL_WEIGHT * structural
        seen[fact.id] = Candidate(fact, round(sim, 3), structural, breakdown, round(score, 3), "vector")

    for fact in await _structural_candidates(session, source):
        if fact.id in seen:
            continue
        structural, breakdown = structural_sim(source, fact)
        # No ANN signal for this path (already looked at vector top-k); the
        # structural evidence is strong enough to rank on its own.
        score = STRUCTURAL_WEIGHT * structural
        seen[fact.id] = Candidate(fact, None, structural,
                                  breakdown, round(min(1.0, score), 3), "structural")

    ranked = sorted(seen.values(), key=lambda c: c.hybrid_score, reverse=True)
    return ranked[:limit]


def candidate_out(c: Candidate) -> dict:
    """Serialisable view for the API (matches ``CandidateOut`` = FactOut + extras)."""
    from app.schemas import FactOut

    out = FactOut.model_validate(c.fact).model_dump()
    out["grounding"] = (c.fact.qualifiers or {}).get("grounding", "")
    out["cosine_sim"] = c.cosine_sim
    out["structural_sim"] = c.structural
    out["hybrid_score"] = c.hybrid_score
    out["source"] = c.source
    out["breakdown"] = c.breakdown
    return out