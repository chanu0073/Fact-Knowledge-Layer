"""Aggregate (background) pipeline runner — thin orchestration over the five
stage services. The API layer exposes this as a queued job; the coroutine owns
its own database session and never touches request-scoped objects.

Each stage service is already idempotent and writes its own ProcessingLog rows;
this runner only sequences them and records failures on the document row.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Document, ProcessingLog
from app.services.embedding import embed_document
from app.services.extraction import extract_facts_for_document
from app.services.ingestion import ingest_document
from app.services.normalization import normalize_facts_for_document
from app.services.reasoning import run_relationships_for_document

# Status values that mean "a run is in progress" — the API refuses to enqueue
# another job while any of these is set.
RUNNING_STATUSES = {"QUEUED", "PROCESSING", "PARSING", "EXTRACTING", "NORMALIZING", "EMBEDDING", "REASONING"}

# Public-facing failure message. Raw exception detail (paths/tracebacks) is
# written to the server log only, never stored on the document or returned via
# the API (see F-2).
GENERIC_ERROR = "An unexpected error occurred."

PIPELINE_STAGES = (
    ("ingest", ingest_document),
    ("extract", extract_facts_for_document),
    ("normalize", normalize_facts_for_document),
    ("embed", embed_document),
    ("reason", run_relationships_for_document),
)

# In-flight status marker for each stage — readable and in RUNNING_STATUSES so
# the API/UI treat them as busy states (services set the terminal ones).
_STAGE_MARKS = {
    "ingest": "PARSING",
    "extract": "EXTRACTING",
    "normalize": "NORMALIZING",
    "embed": "EMBEDDING",
    "reason": "REASONING",
}


async def run_pipeline_task(
    doc_id: str,
    sessionmaker: async_sessionmaker | None = None,
) -> dict:
    """Run the full ingest→extract→normalise→embed→reason chain for one
    document in its own session. Idempotent; safe to retry."""
    from app.database import SessionLocal

    maker = sessionmaker or SessionLocal
    summary: dict = {"document_id": doc_id, "stages": {}}

    async with maker() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            summary["error"] = "document not found"
            return summary

        for stage, fn in PIPELINE_STAGES:
            doc.status = _STAGE_MARKS[stage]
            await session.commit()
            try:
                result = await fn(session, doc)
                summary["stages"][stage] = result
                await session.commit()
            except Exception as exc:
                await session.rollback()
                print(
                    f"[api-error] pipeline stage '{stage}' failed for document {doc_id}: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                doc = await session.get(Document, doc_id)
                if doc is not None:
                    doc.status = "FAILED"
                    doc.error_message = GENERIC_ERROR
                    session.add(ProcessingLog(
                        document_id=doc.id,
                        stage="pipeline",
                        message=f"{stage} failed",
                        meta_json={"stage": stage},
                    ))
                    await session.commit()
                summary["failed"] = stage
                summary["error"] = GENERIC_ERROR
                return summary

    # Cross-document reasoning pass so pairs between this and other docs are
    # produced too (mirrors scripts.run_pipeline).
    try:
        async with maker() as session:
            all_docs = (await session.execute(select(Document))).scalars().all()
            for other in all_docs:
                await run_relationships_for_document(session, other)
            await session.commit()
    except Exception:
        await asyncio.sleep(0)  # cross-doc pass is best-effort
    return summary