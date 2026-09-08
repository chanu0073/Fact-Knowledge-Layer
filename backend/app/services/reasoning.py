"""Phase 8 — document-level relationship pipeline.

Runs the L1→(L2)→L3 decision over a document's facts: for every fact, retrieve
cross-document candidates (Phase 7) and reason each pair. Idempotent: pairs
already stored in ``relationships`` are skipped, as are unrelated pairs.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.factory import get_reasoner
from app.models import Document, Fact, ProcessingLog, Relationship
from app.reasoning.engine import decide_pair
from app.retrieval import retrieve_candidates


async def _stored_pairs(session: AsyncSession) -> set[tuple[str, str]]:
    res = await session.execute(select(Relationship.fact_a_id, Relationship.fact_b_id))
    return {tuple(sorted(r)) for r in res.all()}


async def run_relationships_for_document(
    session: AsyncSession,
    doc: Document,
    reasoner=None,
    *,
    candidate_limit: int | None = None,
    l2_limit: int | None = None,
) -> dict:
    """Reason every candidate pair of a document's facts. Idempotent."""
    reasoner = reasoner or get_reasoner()
    candidate_limit = candidate_limit or settings.reasoning_candidate_limit
    l2_budget = l2_limit if l2_limit is not None else settings.max_l2_calls

    res = await session.execute(select(Fact).where(Fact.document_id == doc.id))
    facts = list(res.scalars().all())

    existing = await _stored_pairs(session)
    by_label: dict[str, int] = defaultdict(int)
    pairs_attempted = stored = skipped = l2_used_total = 0

    for fact in facts:
        candidates = await retrieve_candidates(session, fact, limit=candidate_limit)
        for cand in candidates:
            key = tuple(sorted((fact.id, cand.fact.id)))
            if key in existing:
                continue
            pairs_attempted += 1

            decision = await decide_pair(
                session, fact, cand.fact, reasoner, allow_l2=l2_budget > 0
            )
            if decision is None:
                skipped += 1
                continue
            if decision.l2_used:
                l2_budget -= 1
                l2_used_total += 1

            session.add(Relationship(
                fact_a_id=key[0],
                fact_b_id=key[1],
                relationship_type=decision.label,
                confidence=decision.confidence,
                reasons=decision.reasons,
                evidence_json={
                    "periods_overlap": decision.periods_overlap,
                    "l1_label": decision.l1_label,
                    "l1_strength": decision.l1_strength,
                },
                llm_reasoning=decision.llm_reasoning,
                is_synthetic=decision.is_synthetic,
            ))
            existing.add(key)
            by_label[decision.label] += 1
            stored += 1

    doc.status = "REASONED"
    session.add(ProcessingLog(
        document_id=doc.id,
        stage="reason",
        message=f"stored {stored} relationships for {len(facts)} facts "
                f"({', '.join(f'{k}={v}' for k, v in sorted(by_label.items()))})",
        meta_json={"facts": len(facts), "pairs_attempted": pairs_attempted,
                   "stored": stored, "skipped": skipped, "l2_calls": l2_used_total,
                   "labels": dict(by_label), "reasoner": reasoner.name},
    ))
    return {"facts": len(facts), "pairs_attempted": pairs_attempted,
            "stored": stored, "skipped": skipped, "l2_calls": l2_used_total,
            "labels": dict(by_label), "reasoner": reasoner.name}