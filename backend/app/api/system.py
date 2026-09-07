"""Evaluation cases + dashboard stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Document, EvaluationCase, Evidence, Fact, Relationship
from app.schemas import EvaluationCaseOut, StatsOut

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/evaluation/cases", response_model=list[EvaluationCaseOut])
async def list_cases(session: AsyncSession = Depends(get_db)) -> list[EvaluationCase]:
    res = await session.execute(select(EvaluationCase).order_by(EvaluationCase.kind, EvaluationCase.created_at))
    return list(res.scalars().all())


@router.get("/stats", response_model=StatsOut)
async def stats(session: AsyncSession = Depends(get_db)) -> StatsOut:
    n_docs = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
    n_facts = (await session.execute(select(func.count()).select_from(Fact))).scalar_one()
    n_evidence = (await session.execute(select(func.count()).select_from(Evidence))).scalar_one()
    rel_rows = (await session.execute(select(Relationship.relationship_type, func.count()).group_by(Relationship.relationship_type))).all()
    rel_counts = {k: v for k, v in rel_rows}
    return StatsOut(
        documents=n_docs,
        facts=n_facts,
        evidence=n_evidence,
        relationships=rel_counts,
        provider=settings.llm_provider,
    )