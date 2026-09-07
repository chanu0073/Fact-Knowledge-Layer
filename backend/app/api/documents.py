"""Document upload, listing, and lifecycle endpoints."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Document
from app.schemas import DocumentOut, UploadOut
from app.services.extraction import extract_facts_for_document
from app.services.ingestion import ingest_document
from app.services.normalization import normalize_facts_for_document
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


@router.post("/upload", response_model=UploadOut)
async def upload_documents(
    files: list[UploadFile],
    session: AsyncSession = Depends(get_db),
) -> UploadOut:
    created: list[Document] = []
    for f in files:
        rel, size, sha = await _store_pdf(f)
        doc = Document(
            filename=f.filename or "unnamed.pdf",
            stored_path=rel,
            sha256=sha,
            status="UPLOADED",
        )
        session.add(doc)
        created.append(doc)
    await session.commit()
    for d in created:
        await session.refresh(d)
    return UploadOut(documents=[DocumentOut.model_validate(d) for d in created])


@router.get("", response_model=list[DocumentOut])
async def list_documents(session: AsyncSession = Depends(get_db)) -> list[Document]:
    res = await session.execute(select(Document).order_by(Document.created_at.desc()))
    return list(res.scalars().all())


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, session: AsyncSession = Depends(get_db)) -> Document:
    if not is_valid_uuid(doc_id):
        raise HTTPException(404, "Document not found")
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


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