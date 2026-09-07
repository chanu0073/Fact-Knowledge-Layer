"""Fact queries: listing with filters and detail (with evidence + relationships)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Document, Evidence, Fact, Relationship
from app.schemas import EvidenceOut, FactDetailOut, FactOut, RelationshipOut
from app.utils import is_valid_uuid

router = APIRouter(prefix="/api/facts", tags=["facts"])


def _fact_to_detail(fact: Fact, doc: Document, evidence: list[Evidence], rels: list[Relationship]) -> FactDetailOut:
    return FactDetailOut(
        id=fact.id,
        document_id=fact.document_id,
        evidence_ids=fact.evidence_ids or [],
        entity=fact.entity,
        metric=fact.metric,
        definition=fact.definition,
        raw_value=fact.raw_value,
        numeric_value=fact.numeric_value,
        unit=fact.unit,
        currency=fact.currency,
        value_type=fact.value_type,
        period_raw=fact.period_raw,
        period_start=fact.period_start,
        period_end=fact.period_end,
        period_type=fact.period_type,
        fiscal_year_label=fact.fiscal_year_label,
        observation_type=fact.observation_type,
        scope=fact.scope,
        geography=fact.geography,
        qualifiers=fact.qualifiers or {},
        extraction_confidence=fact.extraction_confidence,
        created_at=fact.created_at,
        document_filename=doc.filename if doc else "",
        evidence=[EvidenceOut.model_validate(e) for e in evidence],
        relationships=[RelationshipOut.model_validate(r) for r in rels],
    )


@router.get("", response_model=list[FactOut])
async def list_facts(
    q: str | None = Query(None),
    document_id: str | None = Query(None),
    entity: str | None = Query(None),
    metric: str | None = Query(None),
    observation_type: str | None = Query(None),
    limit: int = Query(200, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[Fact]:
    stmt = select(Fact)
    if document_id:
        stmt = stmt.where(Fact.document_id == document_id)
    if entity:
        stmt = stmt.where(Fact.entity.ilike(f"%{entity}%"))
    if metric:
        stmt = stmt.where(Fact.metric.ilike(f"%{metric}%"))
    if observation_type:
        stmt = stmt.where(Fact.observation_type == observation_type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Fact.entity.ilike(like),
                Fact.metric.ilike(like),
                Fact.raw_value.ilike(like),
                Fact.period_raw.ilike(like),
            )
        )
    stmt = stmt.order_by(Fact.created_at.desc()).limit(limit)
    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get("/{fact_id}", response_model=FactDetailOut)
async def get_fact(fact_id: str, session: AsyncSession = Depends(get_db)) -> FactDetailOut:
    if not is_valid_uuid(fact_id):
        raise HTTPException(404, "Fact not found")
    fact = await session.get(Fact, fact_id)
    if not fact:
        raise HTTPException(404, "Fact not found")

    docs = (await session.execute(select(Document).where(Document.id == fact.document_id))).scalar_one_or_none()

    evidence = []
    if fact.evidence_ids:
        res = await session.execute(
            select(Evidence).where(Evidence.id.in_(fact.evidence_ids))
        )
        evidence = list(res.scalars().all())

    rels = (
        await session.execute(
            select(Relationship).where(
                or_(Relationship.fact_a_id == fact.id, Relationship.fact_b_id == fact.id)
            )
        )
    ).scalars().all()

    return _fact_to_detail(fact, docs, evidence, list(rels))