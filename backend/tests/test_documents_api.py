"""Phase 10 — document provenance endpoints, pipeline lifecycle, error envelope."""
from __future__ import annotations

import asyncio
import io
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.models import Document, ProcessingLog
from app.services.pipeline import run_pipeline_task

DECK = Path(__file__).resolve().parents[2] / "docs" / "assignment files" / "starter-datasets" / "delhivery" / "03-delhivery-q4-fy24-earnings-presentation.pdf"
needs_dataset = __import__("pytest").mark.skipif(
    not DECK.exists(), reason="local dataset not present"
)

RUNNING = {"QUEUED", "PROCESSING", "PARSING", "EXTRACTING", "EMBEDDING", "REASONING"}


async def _upload_deck(client) -> str:
    files = {"files": ("deck.pdf", io.BytesIO(DECK.read_bytes()), "application/pdf")}
    r = await client.post("/api/documents/upload", files=files)
    assert r.status_code == 200
    return r.json()["documents"][0]["id"]


async def _wait_settled(client, doc_id: str, timeout: float = 60.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        r = await client.get(f"/api/documents/{doc_id}")
        body = r.json()
        if body["status"] not in RUNNING:
            return body
        assert asyncio.get_event_loop().time() < deadline, f"timed out at {body['status']}"
        await asyncio.sleep(0.5)


async def test_404_envelope(client):
    r = await client.get("/api/documents/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


async def test_415_envelope(client):
    files = {"files": ("note.txt", io.BytesIO(b"hello"), "text/plain")}
    r = await client.post("/api/documents/upload", files=files)
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "unsupported_media_type"


async def test_document_filters_and_mode(client, test_sessionmaker):
    async with test_sessionmaker() as session:
        session.add(Document(filename="a.pdf", stored_path="", sha256="s", status="PARSED", data_mode="sample", provider="sample"))
        session.add(Document(filename="b.pdf", stored_path="", sha256="t", status="UPLOADED", data_mode="fixture", provider="fixture"))
        await session.commit()

    r = await client.get("/api/documents", params={"status": "PARSED"})
    assert [d["filename"] for d in r.json()] == ["a.pdf"]
    r = await client.get("/api/documents", params={"data_mode": "fixture"})
    assert [d["filename"] for d in r.json()] == ["b.pdf"]
    assert r.json()[0]["provider"] == "fixture"


@needs_dataset
async def test_document_provenance_endpoints(client, test_sessionmaker):
    doc_id = await _upload_deck(client)
    r = await client.post(f"/api/documents/{doc_id}/process")
    assert r.status_code == 200 and r.json()["status"] == "PARSED"

    # Evidence provenance: page + block + content present.
    r = await client.get(f"/api/documents/{doc_id}/evidence", params={"page_number": 1})
    assert r.status_code == 200
    blocks = r.json()
    assert blocks and all(b["document_id"] == doc_id for b in blocks)
    assert all(isinstance(b["page_number"], int) and isinstance(b["content"], str) for b in blocks)

    # Facts provenance: filename + page + grounding enrichment.
    r = await client.post(f"/api/documents/{doc_id}/extract")
    assert r.status_code == 200 and r.json()["status"] == "EXTRACTED"
    r = await client.get(f"/api/documents/{doc_id}/facts")
    assert r.status_code == 200
    facts = r.json()
    assert facts
    for f in facts:
        assert f["document_filename"] == "deck.pdf"
        assert isinstance(f["page_number"], int)
        assert f["grounding"] in ("block", "page")

    # Processing logs recorded for ingest + extract.
    r = await client.get(f"/api/documents/{doc_id}/logs")
    assert r.status_code == 200
    stages = {log["stage"] for log in r.json()}
    assert {"ingest", "extract"} <= stages


@needs_dataset
async def test_pipeline_background_lifecycle(client, test_sessionmaker):
    """Upload → queue full pipeline → assert REASONED with facts + logs."""
    doc_id = await _upload_deck(client)
    r = await client.post(f"/api/documents/{doc_id}/pipeline")
    assert r.status_code == 202
    assert r.json()["queued"] is True
    assert r.json()["document"]["status"] == "QUEUED"

    settled = await _wait_settled(client, doc_id)
    assert settled["status"] == "REASONED", settled.get("error_message")

    r = await client.get(f"/api/documents/{doc_id}/facts")
    assert r.json()
    r = await client.get(f"/api/documents/{doc_id}/logs")
    stages = {log["stage"] for log in r.json()}
    assert {"ingest", "extract", "normalize", "embed", "reason"} <= stages


async def test_pipeline_conflict_while_running(client, test_sessionmaker):
    assert await _pipeline_conflict(client, test_sessionmaker, "QUEUED") == 409


async def test_pipeline_conflict_while_normalizing(client, test_sessionmaker):
    """Regression: NORMALIZING must be treated as a running pipeline state,
    so a second call is refused with 409 instead of racing the task."""
    assert await _pipeline_conflict(client, test_sessionmaker, "NORMALIZING") == 409


async def _pipeline_conflict(client, sessionmaker, status: str) -> int:
    async with sessionmaker() as session:
        doc = Document(
            filename=f"{status.lower()}.pdf",
            stored_path="",
            sha256="",
            status=status,
            data_mode="sample",
            provider="sample",
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    r = await client.post(f"/api/documents/{doc_id}/pipeline")
    assert r.json()["error"]["code"] == "conflict"
    return r.status_code


async def test_documents_stats_mode_counts(client, test_sessionmaker):
    async with test_sessionmaker() as session:
        session.add(Document(filename="s.pdf", stored_path="", sha256="1", status="REASONED", data_mode="sample", provider="sample"))
        session.add(Document(filename="f.pdf", stored_path="", sha256="2", status="EMBEDDED", data_mode="fixture", provider="fixture"))
        await session.commit()

    r = await client.get("/api/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["documents_by_mode"] == {"sample": 1, "fixture": 1}
    assert s["data_mode"] in ("sample", "live-llm")


async def test_stage_500_does_not_leak_internals(client, test_sessionmaker):
    """Regression (F-2): a failing stage endpoint must return the standard
    error envelope with a generic message — never the raw exception text,
    traceback, or an absolute server path (e.g. the upload dir)."""
    async with test_sessionmaker() as session:
        doc = Document(
            filename="broken.pdf",
            stored_path="missing-file.pdf",  # nothing on disk -> FileNotFoundError
            sha256="",
            status="UPLOADED",
            data_mode="sample",
            provider="sample",
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    r = await client.post(f"/api/documents/{doc_id}/process")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An unexpected error occurred."

    raw = r.text
    assert str(settings.upload_dir) not in raw          # no absolute server path
    assert "data/uploads" not in raw
    assert "Traceback" not in raw                       # no traceback
    assert "FileNotFoundError" not in raw               # no exception class
    assert "[Errno" not in raw
    assert "Stored PDF missing" not in raw              # no raw exception text

    # The sanitised message is also what persists on the document row.
    r = await client.get(f"/api/documents/{doc_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "FAILED"
    assert r.json()["error_message"] == "An unexpected error occurred."


async def test_pipeline_failure_sanitizes_stored_error(client, test_sessionmaker):
    """Regression (F-2): the background pipeline must not persist raw exception
    text on the document row or in the (public) processing log when those values
    are returned through the API."""
    async with test_sessionmaker() as session:
        doc = Document(
            filename="broken-pipeline.pdf",
            stored_path="missing-file.pdf",
            sha256="",
            status="UPLOADED",
            data_mode="sample",
            provider="sample",
        )
        session.add(doc)
        await session.commit()
        doc_id = doc.id

    summary = await run_pipeline_task(doc_id, test_sessionmaker)

    assert summary["failed"] == "ingest"
    assert summary["error"] == "An unexpected error occurred."

    async with test_sessionmaker() as session:
        doc = await session.get(Document, doc_id)
        assert doc.status == "FAILED"
        assert doc.error_message == "An unexpected error occurred."
        logs = (
            await session.execute(
                select(ProcessingLog).where(ProcessingLog.document_id == doc_id)
            )
        ).scalars().all()
        assert logs
        assert all("FileNotFoundError" not in (log.message or "") for log in logs)
        assert all("missing-file.pdf" not in (log.message or "") for log in logs)
        assert all("failed" in (log.message or "") for log in logs)