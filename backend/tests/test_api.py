"""API smoke tests: health, empty lists, document upload/list."""
from __future__ import annotations

import io

import pytest

from tests.conftest import TEST_DB  # noqa: F401


def _pdf_bytes():
    # Minimal valid PDF (1 blank page). Good enough to exercise storage logic.
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\nxref\n0 4\n0000000000 65535 f \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "db_ok" in body


async def test_empty_lists(client):
    assert (await client.get("/api/documents")).json() == []
    assert (await client.get("/api/facts")).json() == []
    assert (await client.get("/api/relationships")).json() == []


async def test_upload_and_list(client):
    files = {"files": ("blank.pdf", io.BytesIO(_pdf_bytes()), "application/pdf")}
    r = await client.post("/api/documents/upload", files=files)
    assert r.status_code == 200
    docs = r.json()["documents"]
    assert len(docs) == 1
    assert docs[0]["filename"] == "blank.pdf"
    assert docs[0]["status"] == "UPLOADED"
    assert docs[0]["sha256"]

    listing = (await client.get("/api/documents")).json()
    assert len(listing) == 1
    assert listing[0]["id"] == docs[0]["id"]


async def test_upload_rejects_non_pdf(client):
    files = {"files": ("note.txt", io.BytesIO(b"hello"), "text/plain")}
    r = await client.post("/api/documents/upload", files=files)
    assert r.status_code == 415


async def test_stats_empty(client):
    r = await client.get("/api/stats")
    assert r.status_code == 200
    s = r.json()
    assert s["documents"] == 0 and s["facts"] == 0 and s["relationships"] == {}