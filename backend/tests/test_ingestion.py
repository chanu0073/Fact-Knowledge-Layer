"""API-level tests for the Phase-3 process (ingest) endpoint."""
from __future__ import annotations

import io
import shutil
from pathlib import Path

from sqlalchemy import select, func

from app.models import Document, Evidence, ProcessingLog

DECK = Path(__file__).resolve().parents[2] / "docs" / "assignment files" / "starter-datasets" / "delhivery" / "03-delhivery-q4-fy24-earnings-presentation.pdf"
needs_dataset = __import__("pytest").mark.skipif(
    not DECK.exists(), reason="local dataset not present"
)


def _tiny_pdf_bytes():
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n0\n%%EOF\n"
    )


async def test_process_updates_document(client):
    files = {"files": ("blank.pdf", io.BytesIO(_tiny_pdf_bytes()), "application/pdf")}
    doc_id = (await client.post("/api/documents/upload", files=files)).json()["documents"][0]["id"]

    r = await client.post(f"/api/documents/{doc_id}/process")
    assert r.status_code == 200
    body = r.json()
    assert body["page_count"] == 1
    assert body["status"] == "PARSED"

    listing = (await client.get("/api/documents")).json()
    assert listing[0]["page_count"] == 1
    assert listing[0]["status"] == "PARSED"


async def test_process_missing_document_404(client):
    r = await client.post("/api/documents/nope/process")
    assert r.status_code == 404


@needs_dataset
async def test_process_real_pdf_creates_evidence(client, test_sessionmaker):
    # Upload a real deck via the API, then process and check evidence rows.
    fbytes = DECK.read_bytes()
    files = {"files": ("deck.pdf", io.BytesIO(fbytes), "application/pdf")}
    doc_id = (await client.post("/api/documents/upload", files=files)).json()["documents"][0]["id"]

    r = await client.post(f"/api/documents/{doc_id}/process")
    assert r.status_code == 200
    assert r.json()["status"] == "PARSED"
    assert r.json()["page_count"] == 27

    async with test_sessionmaker() as session:
        ev_count = (await session.execute(select(func.count()).select_from(Evidence).where(Evidence.document_id == doc_id))).scalar_one()
        assert ev_count > 0
        doc = await session.get(Document, doc_id)
        assert doc.status == "PARSED"
        assert doc.page_count == 27
        # Table evidence captured on the earnings deck (financial tables exist).
        t_count = (await session.execute(select(func.count()).select_from(Evidence).where(Evidence.document_id == doc_id, Evidence.evidence_type == "table"))).scalar_one()
        assert t_count > 0
        # Processing log recorded.
        logs = (await session.execute(select(ProcessingLog).where(ProcessingLog.document_id == doc_id))).scalars().all()
        assert any(l.stage == "ingest" for l in logs)


@needs_dataset
async def test_reprocess_is_idempotent(client, test_sessionmaker):
    fbytes = DECK.read_bytes()
    files = {"files": ("deck.pdf", io.BytesIO(fbytes), "application/pdf")}
    doc_id = (await client.post("/api/documents/upload", files=files)).json()["documents"][0]["id"]
    await client.post(f"/api/documents/{doc_id}/process")
    await client.post(f"/api/documents/{doc_id}/process")

    async with test_sessionmaker() as session:
        ev_count = (await session.execute(select(func.count()).select_from(Evidence).where(Evidence.document_id == doc_id))).scalar_one()
        doc = await session.get(Document, doc_id)
        assert doc.status == "PARSED"
        # Rows replaced, not doubled.
        assert ev_count == ev_count  # sanity: query returns current rows
        p_ev = (await session.execute(
            select(Evidence).where(Evidence.document_id == doc_id).order_by(Evidence.page_number, Evidence.block_index)
        )).scalars().all()
        after = len(p_ev)
        assert after > 0
        # Re-run again and confirm same count.
        await client.post(f"/api/documents/{doc_id}/process")
        async with test_sessionmaker() as session2:
            again = (await session2.execute(
                select(func.count()).select_from(Evidence).where(Evidence.document_id == doc_id)
            )).scalar_one()
        assert again == after