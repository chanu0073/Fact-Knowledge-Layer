"""Evaluation cases, results, dashboard stats."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import APIError
from app.config import settings
from app.database import get_db
from app.evaluation.cases import CASES
from app.models import Document, EvaluationCase, Evidence, Fact, Relationship
from app.schemas import EvaluationCaseOut, EvaluationResultOut, EvaluationRunOut, StatsOut
from app.services.evaluation import case_statuses, run_evaluation

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/evaluation/cases", response_model=list[EvaluationCaseOut])
async def list_cases(session: AsyncSession = Depends(get_db)) -> list[EvaluationCase]:
    res = await session.execute(select(EvaluationCase).order_by(EvaluationCase.kind, EvaluationCase.created_at))
    return list(res.scalars().all())


@router.get("/evaluation/results", response_model=list[EvaluationResultOut])
async def evaluation_results(session: AsyncSession = Depends(get_db)) -> list[dict]:
    """Static per-case outcome (PASS/FAIL/PENDING/NOT_REGISTERED) derived from
    the persisted registration rows — read-only, never reasons live."""
    rows = await case_statuses(session)
    return [{**r, "data_mode": settings.data_mode} for r in rows]


@router.post("/evaluation/run", response_model=list[EvaluationRunOut])
async def evaluation_run(session: AsyncSession = Depends(get_db)) -> list[dict]:
    """Re-run the reasoner over all cases and compare to expectations.

    Sample-only via the API: a live-LLM re-run is a quota-burning operation and
    must go through the script path (scripts.evaluate) so the operator controls
    volume.
    """
    if settings.data_mode != "sample":
        raise APIError(409, "conflict", "Live-LLM re-runs must use the script (scripts.evaluate), not the API")
    results = await run_evaluation(session, CASES)
    out: list[dict] = []
    for r in results:
        actual = None if r["actual"] in ("PENDING", "NO_RELATIONSHIP") else r["actual"]
        if actual is None:
            # Facts missing -> unresolved (PENDING). Facts present but the
            # reasoner declined -> a real mismatch (FAIL). Kept semantically
            # distinct from every relationship label.
            outcome = "PENDING" if r.get("reason") == "facts not found in corpus" else "FAIL"
        else:
            outcome = "PASS" if r.get("match") else "FAIL"
        out.append({
            "case_key": r["key"],
            "kind": next(c.kind for c in CASES if c.key == r["key"]),
            "title": next(c.title for c in CASES if c.key == r["key"]),
            "source": next(c.source for c in CASES if c.key == r["key"]),
            "expected": r["expected"],
            "actual": actual,
            "outcome": outcome,
            "confidence": r.get("confidence", 0.0),
            "reasons": r.get("reasons") or [],
            "note": r.get("reason", ""),
            "data_mode": settings.data_mode,
        })
    return out


@router.get("/stats", response_model=StatsOut)
async def stats(session: AsyncSession = Depends(get_db)) -> StatsOut:
    n_docs = (await session.execute(select(func.count()).select_from(Document))).scalar_one()
    n_facts = (await session.execute(select(func.count()).select_from(Fact))).scalar_one()
    n_evidence = (await session.execute(select(func.count()).select_from(Evidence))).scalar_one()
    n_cases = (await session.execute(select(func.count()).select_from(EvaluationCase))).scalar_one()
    rel_rows = (await session.execute(select(Relationship.relationship_type, func.count()).group_by(Relationship.relationship_type))).all()
    rel_counts = {k: v for k, v in rel_rows}
    mode_rows = (await session.execute(select(Document.data_mode, func.count()).group_by(Document.data_mode))).all()
    documents_by_mode = {k or "sample": v for k, v in mode_rows}
    return StatsOut(
        documents=n_docs,
        facts=n_facts,
        evidence=n_evidence,
        relationships=rel_counts,
        provider=settings.llm_provider,
        embedding_provider=settings.embedding_provider,
        data_mode=settings.data_mode,
        cases=n_cases,
        documents_by_mode=documents_by_mode,
    )