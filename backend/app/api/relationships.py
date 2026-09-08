"""Relationship queries (list + detail)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document, Evidence, Fact, Relationship
from app.schemas import EvidenceOut, RelationshipDetailOut, RelationshipFactOut, RelationshipOut
from app.utils import is_valid_uuid

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


async def _relationship_fact_side(session: AsyncSession, fact: Fact | None) -> RelationshipFactOut | None:
    """Embed a fact with its own evidence so the doc → page → block trace is
    self-contained in the relationship view."""
    if fact is None:
        return None
    doc = (await session.execute(select(Document).where(Document.id == fact.document_id))).scalar_one_or_none()
    evidence: list[Evidence] = []
    if fact.evidence_ids:
        res = await session.execute(select(Evidence).where(Evidence.id.in_(fact.evidence_ids)))
        evidence = list(res.scalars().all())
    base = RelationshipFactOut.model_validate(fact)
    return base.model_copy(update={
        "document_filename": doc.filename if doc else "",
        "evidence": [EvidenceOut.model_validate(e) for e in evidence],
        "grounding": (fact.qualifiers or {}).get("grounding", ""),
    })


@router.get("", response_model=list[RelationshipOut])
async def list_relationships(
    relationship_type: str | None = Query(None),
    fact_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[Relationship]:
    stmt = select(Relationship)
    if relationship_type:
        stmt = stmt.where(Relationship.relationship_type == relationship_type)
    if fact_id:
        stmt = stmt.where(or_(Relationship.fact_a_id == fact_id, Relationship.fact_b_id == fact_id))
    stmt = stmt.order_by(Relationship.created_at.desc()).limit(limit).offset(offset)
    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get("/{rel_id}", response_model=RelationshipDetailOut)
async def get_relationship(rel_id: str, session: AsyncSession = Depends(get_db)) -> RelationshipDetailOut:
    if not is_valid_uuid(rel_id):
        raise HTTPException(404, "Relationship not found")
    rel = await session.get(Relationship, rel_id)
    if not rel:
        raise HTTPException(404, "Relationship not found")

    fa = await session.get(Fact, rel.fact_a_id)
    fb = await session.get(Fact, rel.fact_b_id)
    return RelationshipDetailOut(
        id=rel.id,
        fact_a_id=rel.fact_a_id,
        fact_b_id=rel.fact_b_id,
        relationship_type=rel.relationship_type,
        confidence=rel.confidence,
        reasons=rel.reasons or [],
        llm_reasoning=rel.llm_reasoning or "",
        is_synthetic=rel.is_synthetic,
        created_at=rel.created_at,
        fact_a=await _relationship_fact_side(session, fa),
        fact_b=await _relationship_fact_side(session, fb),
    )