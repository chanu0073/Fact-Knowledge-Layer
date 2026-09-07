"""Relationship queries (list + detail)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Fact, Relationship
from app.schemas import FactOut, RelationshipDetailOut, RelationshipOut
from app.utils import is_valid_uuid

router = APIRouter(prefix="/api/relationships", tags=["relationships"])


@router.get("", response_model=list[RelationshipOut])
async def list_relationships(
    relationship_type: str | None = Query(None),
    fact_id: str | None = Query(None),
    limit: int = Query(200, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[Relationship]:
    stmt = select(Relationship)
    if relationship_type:
        stmt = stmt.where(Relationship.relationship_type == relationship_type)
    if fact_id:
        stmt = stmt.where(or_(Relationship.fact_a_id == fact_id, Relationship.fact_b_id == fact_id))
    stmt = stmt.order_by(Relationship.created_at.desc()).limit(limit)
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
        fact_a=FactOut.model_validate(fa) if fa else None,
        fact_b=FactOut.model_validate(fb) if fb else None,
    )