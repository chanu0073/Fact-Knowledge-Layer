"""Document ingestion: PDF on disk → evidence rows in the DB.

Evidence is the provenance layer. Every row links a document to a
(page_number, block_index, evidence_type, content) and carries where on the
page it came from (location_json) so later stages can quote it exactly.
"""
from __future__ import annotations

from pathlib import Path

import anyio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Document, Evidence, ProcessingLog
from app.processing.pdf_parser import parse_pdf


def evidence_row(
    document_id: str,
    block: object,
    evidence_type: str,
) -> Evidence:
    """Build an Evidence ORM row from a parsed text/table block."""
    from app.processing.pdf_parser import TableBlock, TextBlock

    if isinstance(block, (TextBlock, TableBlock)):
        return Evidence(
            document_id=document_id,
            page_number=block.page_number,
            block_index=block.block_index,
            evidence_type=evidence_type,
            content=block.content,
            location_json=block.to_evidence(),
        )
    raise TypeError(f"Unsupported block type: {type(block)!r}")


async def ingest_document(session: AsyncSession, doc: Document) -> int:
    """Parse a stored PDF and persist its evidence blocks.

    Returns the number of evidence rows written. Idempotent: re-running
    replaces the document's evidence.
    """
    path = settings.upload_dir / doc.stored_path
    if not path.exists():
        raise FileNotFoundError(f"Stored PDF missing: {path}")

    # PDF parsing is CPU/IO-bound; run it off the event loop in a worker thread.
    parsed = await anyio.to_thread.run_sync(lambda: parse_pdf(Path(path)))

    # Idempotent re-run: drop previous evidence for this document.
    await session.execute(delete(Evidence).where(Evidence.document_id == doc.id))

    rows = []
    for block in parsed.text_blocks:
        rows.append(evidence_row(doc.id, block, "text"))
    for table in parsed.tables:
        rows.append(evidence_row(doc.id, table, "table"))

    session.add_all(rows)

    doc.page_count = parsed.page_count
    doc.status = "PARSED"

    for err in parsed.errors:
        session.add(ProcessingLog(document_id=doc.id, stage="ingest", message=err))

    session.add(ProcessingLog(
        document_id=doc.id,
        stage="ingest",
        message=f"parsed {parsed.page_count} pages, {len(rows)} evidence blocks",
        meta_json={"text_blocks": len(parsed.text_blocks), "tables": len(parsed.tables)},
    ))
    return len(rows)