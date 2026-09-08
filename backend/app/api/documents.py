"""Document upload, listing, lifecycle, provenance endpoints."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import build_fact_items
from app.api.errors import APIError
from app.config import settings
from app.database import get_db
from app.models import Document, Evidence, ProcessingLog
from app.schemas import DocumentOut, EvidenceOut, FactOut, PipelineQueuedOut, ProcessingLogOut, UploadOut
from app.services.embedding import embed_document
from app.services.extraction import extract_facts_for_document
from app.services.ingestion import ingest_document
from app.services.normalization import normalize_facts_for_document
from app.services.pipeline import RUNNING_STATUSES, run_pipeline_task
from app.services.reasoning import run_relationships_for_document
from app.utils import is_valid_uuid

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _ensure_upload_dir() -> Path:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir


async def _store_pdf(file: UploadFile) -> tuple[str, int, str]:
    """Persist upload to disk; return (stored_relpath, byte_size, sha256)."""
    data = await file.read()
    if not data:
        raise HTTPException(400, f"File {file.filename} is empty")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File {file.filename} exceeds {settings.max_upload_mb} MB")
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, f"File {file.filename} is not a PDF")

    sha = hashlib.sha256(data).hexdigest()
    doc_id = str(uuid.uuid4())
    rel = f"{doc_id}.pdf"
    dest = _ensure_upload_dir() / rel
    dest.write_bytes(data)
    return rel, len(data), sha


def _new_document(filename: str, rel: str, sha: str) -> Document:
    """Create a document row stamped with the provider mode in effect. This is
    the single creation point so sample vs live-llm provenance is never mixed."""
    return Document(
        filename=filename,
        stored_path=rel,
        sha256=sha,
        status="UPLOADED",
        data_mode=settings.data_mode,
        provider=settings.llm_provider,
    )


@router.post("/upload", response_model=UploadOut)
async def upload_documents(
    files: list[UploadFile],
    session: AsyncSession = Depends(get_db),
) -> UploadOut:
    created: list[Document] = []
    for f in files:
        rel, size, sha = await _store_pdf(f)
        doc = _new_document(f.filename or "unnamed.pdf", rel, sha)
        session.add(doc)
        created.append(doc)
    await session.commit()
    for d in created:
        await session.refresh(d)
    return UploadOut(documents=[DocumentOut.model_validate(d) for d in created])


@router.get("", response_model=list[DocumentOut])
async def list_documents(
    status: str | None = Query(None),
    data_mode: str | None = Query(None),
    limit: int = Query(0, ge=0),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[Document]:
    stmt = select(Document).order_by(Document.created_at.desc())
    if status:
        stmt = stmt.where(Document.status == status)
    if data_mode:
        stmt = stmt.where(Document.data_mode == data_mode)
    if limit:
        stmt = stmt.limit(limit).offset(offset)
    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, session: AsyncSession = Depends(get_db)) -> Document:
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("/{doc_id}/evidence", response_model=list[EvidenceOut])
async def get_document_evidence(
    doc_id: str,
    page_number: int | None = Query(None, ge=1),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[Evidence]:
    """Evidence blocks (document → page → block provenance) for a document."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    if await session.get(Document, doc_id) is None:
        raise HTTPException(404, "Document not found")
    stmt = (
        select(Evidence)
        .where(Evidence.document_id == doc_id)
        .order_by(Evidence.page_number, Evidence.block_index)
        .limit(limit)
        .offset(offset)
    )
    if page_number:
        stmt = stmt.where(Evidence.page_number == page_number)
    res = await session.execute(stmt)
    return list(res.scalars().all())


@router.get("/{doc_id}/facts", response_model=list[FactOut])
async def get_document_facts(
    doc_id: str,
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[FactOut]:
    """Facts of one document, enriched with document filename + source pages."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    if await session.get(Document, doc_id) is None:
        raise HTTPException(404, "Document not found")
    from app.models import Fact

    res = await session.execute(
        select(Fact).where(Fact.document_id == doc_id).order_by(Fact.created_at.desc()).limit(limit).offset(offset)
    )
    return await build_fact_items(session, list(res.scalars().all()))


@router.get("/{doc_id}/logs", response_model=list[ProcessingLogOut])
async def get_document_logs(
    doc_id: str,
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[ProcessingLog]:
    """Pipeline observability: ingest/extract/embed/reason + failure rows."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    if await session.get(Document, doc_id) is None:
        raise HTTPException(404, "Document not found")
    res = await session.execute(
        select(ProcessingLog)
        .where(ProcessingLog.document_id == doc_id)
        .order_by(ProcessingLog.created_at.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


@router.post("/{doc_id}/pipeline", response_model=PipelineQueuedOut, status_code=202)
async def pipeline_document(
    doc_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Queue the full ingest→extract→normalise→embed→reason chain in the
    background; poll GET /documents/{id} for progress (status transitions +
    processing logs). 409 while a run is already in progress."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status in RUNNING_STATUSES:
        raise APIError(409, "conflict", f"Document is already processing (status={doc.status})")

    doc.status = "QUEUED"
    await session.commit()
    maker = getattr(request.app.state, "sessionmaker", None)
    background_tasks.add_task(run_pipeline_task, doc_id, maker)
    return PipelineQueuedOut(
        document=DocumentOut.model_validate(doc),
        note="pipeline queued; poll document status",
    )


@router.post("/{doc_id}/process", response_model=DocumentOut)
async def process_document(doc_id: str, session: AsyncSession = Depends(get_db)) -> Document:
    """Parse a stored PDF into evidence blocks (Phase 3 ingest). Idempotent."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    doc.status = "PARSING"
    await session.commit()

    try:
        await ingest_document(session, doc)
        await session.commit()
        doc = await session.get(Document, doc_id)
        return doc
    except Exception as exc:
        await session.rollback()
        doc = await session.get(Document, doc_id)
        if doc:
            doc.status = "FAILED"
            doc.error_message = str(exc)[:2000]
            await session.commit()
        raise HTTPException(500, f"Processing failed: {exc}") from exc


@router.post("/{doc_id}/extract", response_model=DocumentOut)
async def extract_document(doc_id: str, session: AsyncSession = Depends(get_db)) -> Document:
    """Run fact extraction over a parsed document's evidence. Idempotent."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status in ("UPLOADED", "FAILED"):
        raise HTTPException(409, f"Document not ready for extraction (status={doc.status})")

    doc.status = "EXTRACTING"
    await session.commit()
    try:
        await extract_facts_for_document(session, doc)
        await session.commit()
        doc = await session.get(Document, doc_id)
        return doc
    except Exception as exc:
        await session.rollback()
        doc = await session.get(Document, doc_id)
        if doc:
            doc.status = "FAILED"
            doc.error_message = str(exc)[:2000]
            await session.commit()
        raise HTTPException(500, f"Extraction failed: {exc}") from exc


@router.post("/{doc_id}/normalize", response_model=DocumentOut)
async def normalize_document(doc_id: str, session: AsyncSession = Depends(get_db)) -> Document:
    """Canonicalise value/unit/period fields on a document's facts. Idempotent."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status in ("UPLOADED", "FAILED"):
        raise HTTPException(409, f"Document not ready for normalisation (status={doc.status})")

    try:
        await normalize_facts_for_document(session, doc)
        await session.commit()
        doc = await session.get(Document, doc_id)
        return doc
    except Exception as exc:
        await session.rollback()
        doc = await session.get(Document, doc_id)
        if doc:
            doc.status = "FAILED"
            doc.error_message = str(exc)[:2000]
            await session.commit()
        raise HTTPException(500, f"Normalisation failed: {exc}") from exc


@router.post("/{doc_id}/embed", response_model=DocumentOut)
async def embed_document_endpoint(doc_id: str, session: AsyncSession = Depends(get_db)) -> Document:
    """Compute + store embeddings for a document's facts. Idempotent."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status in ("UPLOADED", "FAILED"):
        raise HTTPException(409, f"Document not ready for embedding (status={doc.status})")

    doc.status = "EMBEDDING"
    await session.commit()
    try:
        await embed_document(session, doc)
        await session.commit()
        doc = await session.get(Document, doc_id)
        return doc
    except Exception as exc:
        await session.rollback()
        doc = await session.get(Document, doc_id)
        if doc:
            doc.status = "FAILED"
            doc.error_message = str(exc)[:2000]
            await session.commit()
        raise HTTPException(500, f"Embedding failed: {exc}") from exc


@router.post("/{doc_id}/reason", response_model=DocumentOut)
async def reason_document(doc_id: str, session: AsyncSession = Depends(get_db)) -> Document:
    """Run the relationship reasoning pass over a document's facts. Idempotent."""
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status in ("UPLOADED", "FAILED"):
        raise HTTPException(409, f"Document not ready for reasoning (status={doc.status})")

    doc.status = "REASONING"
    await session.commit()
    try:
        await run_relationships_for_document(session, doc)
        await session.commit()
        doc = await session.get(Document, doc_id)
        return doc
    except Exception as exc:
        await session.rollback()
        doc = await session.get(Document, doc_id)
        if doc:
            doc.status = "FAILED"
            doc.error_message = str(exc)[:2000]
            await session.commit()
        raise HTTPException(500, f"Reasoning failed: {exc}") from exc