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
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc