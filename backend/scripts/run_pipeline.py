"""Run the full pipeline over one or more PDFs: ingest → extract → normalise →
embed → reason. Idempotent per filename (existing documents are skipped).

Usage:
    cd backend
    LLM_PROVIDER=sample EMBEDDING_PROVIDER=sample \
      POSTGRES_HOST=localhost .venv/bin/python -m scripts.run_pipeline \
      "<pdf path 1>" "<pdf path 2>" ...
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import Document
from app.services.embedding import embed_document
from app.services.extraction import extract_facts_for_document
from app.services.ingestion import ingest_document
from app.services.normalization import normalize_facts_for_document
from app.services.reasoning import run_relationships_for_document


async def run_one(session, path: Path) -> dict:
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    filename = path.name

    doc = (await session.execute(select(Document).where(Document.filename == filename))).scalar_one_or_none()
    if doc is not None:
        return {"filename": filename, "skipped": True, "status": doc.status}

    dest = settings.upload_dir / f"{uuid.uuid4()}.pdf"
    dest.write_bytes(data)

    doc = Document(filename=filename, stored_path=dest.name, sha256=sha, status="UPLOADED",
                   data_mode=settings.data_mode, provider=settings.llm_provider)
    session.add(doc)
    await session.flush()

    await ingest_document(session, doc)
    await extract_facts_for_document(session, doc)
    await normalize_facts_for_document(session, doc)
    await embed_document(session, doc)
    await run_relationships_for_document(session, doc)
    return {"filename": filename, "skipped": False, "status": doc.status}


async def main(paths: list[str]) -> None:
    results = []
    async with SessionLocal() as session:
        for p in paths:
            path = Path(p)
            if not path.exists():
                print(f"[skip] missing: {p}")
                continue
            try:
                res = await run_one(session, path)
                results.append(res)
                print(f"[{'skip' if res['skipped'] else 'ok '}] {res['filename']} -> {res['status']}")
            except Exception as exc:
                await session.rollback()
                print(f"[fail] {path.name}: {exc}")
                results.append({"filename": path.name, "skipped": False, "status": f"FAILED: {exc}"})
        try:
            await session.commit()
        except Exception as exc:
            await session.rollback()
            print(f"[commit failed] {exc}")

        # One more reasoning pass over every document so cross-document pairs
        # between *newly* ingested docs are also produced.
        docs = (await session.execute(select(Document))).scalars().all()
        for doc in docs:
            try:
                await run_relationships_for_document(session, doc)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                print(f"[reason-all failed for {doc.filename}]: {exc}")

    print("\nDone.")
    return results


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))