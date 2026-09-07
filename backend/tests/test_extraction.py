"""Phase 4: extraction pipeline tests (sample adapter, deterministic)."""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.llm.adapters.sample import SampleExtractor
from app.llm.base import EvidenceBlockSpec, ExtractedFact
from app.models import Evidence, Fact, ProcessingLog

DECK = Path(__file__).resolve().parents[2] / "docs" / "assignment files" / "starter-datasets" / "delhivery" / "03-delhivery-q4-fy24-earnings-presentation.pdf"
needs_dataset = pytest.mark.skipif(
    not DECK.exists(), reason="local dataset not present"
)

pdf_bytes = DECK.read_bytes() if DECK.exists() else b""


def _specs() -> list[EvidenceBlockSpec]:
    # A tiny, generic evidence set exercising number parsing (no doc specifics).
    return [
        EvidenceBlockSpec(index=0, page_number=1, evidence_type="text", content="For the year ended March 31, 2024, revenue was Rs 81,415.38 million."),
        EvidenceBlockSpec(index=1, page_number=1, evidence_type="text", content="EBITDA margin improved to 14.2% from 9.8%."),
        EvidenceBlockSpec(index=2, page_number=1, evidence_type="table", content="Particulars | FY2024 | FY2023\nNet worth | 4,590.12 | 3,921.00\nDebt | 120.5 | 150.0"),
        EvidenceBlockSpec(index=3, page_number=1, evidence_type="text", content="The board of directors met on Thursday."),
    ]


@pytest.fixture
def sample():
    return SampleExtractor()


async def test_sample_adapter_extracts_generic_facts(sample):
    facts = await sample.extract(_specs())
    assert isinstance(facts, list) and facts
    numbers = [f.numeric_value for f in facts if f.numeric_value is not None]
    assert 81415.38 in [round(n, 2) for n in numbers]
    # table facts carry header context / units
    table_facts = [f for f in facts if f.qualifiers.get("extractor") == "sample" and "table_row" in f.qualifiers]
    assert table_facts
    # non-numeric "board of directors" block must NOT produce a fact
    assert not any("board of directors" in f.metric for f in facts)


async def test_sample_adapter_no_numbers_returns_empty(sample):
    blocks = [EvidenceBlockSpec(index=0, page_number=1, evidence_type="text", content="The board met on Thursday.")]
    assert await sample.extract(blocks) == []


async def test_extraction_writes_grounded_facts(client, test_sessionmaker):
    # upload + parse + extract a real deck via the API
    if not DECK.exists():
        pytest.skip("local dataset not present")
    files = {"files": ("deck.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    doc_id = (await client.post("/api/documents/upload", files=files)).json()["documents"][0]["id"]
    assert (await client.post(f"/api/documents/{doc_id}/process")).json()["status"] == "PARSED"

    r = await client.post(f"/api/documents/{doc_id}/extract")
    assert r.status_code == 200
    assert r.json()["status"] == "EXTRACTED"

    async with test_sessionmaker() as session:
        facts = (await session.execute(select(Fact).where(Fact.document_id == doc_id))).scalars().all()
        assert facts, "expected at least one extracted fact from the deck"

        orphan = [f for f in facts if not f.evidence_ids]
        assert not orphan, "every fact must be grounded in evidence"

        page_grounded = [f for f in facts if f.qualifiers.get("grounding") == "page"]
        assert not page_grounded, "sample adapter links blocks, so none should fall back to whole-page grounding"

        confs = [f.extraction_confidence for f in facts]
        assert all(0.0 <= c <= 1.0 for c in confs)

        logs = (await session.execute(select(ProcessingLog).where(ProcessingLog.document_id == doc_id))).scalars().all()
        assert any(l.stage == "extract" for l in logs)

        # facts link to existing evidence ids
        evids = set((await session.execute(select(Evidence.id).where(Evidence.document_id == doc_id))).scalars().all())
        for f in facts:
            assert set(f.evidence_ids) <= evids


async def test_extract_before_parse_is_409(client):
    files = {"files": ("blank.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")}
    doc_id = (await client.post("/api/documents/upload", files=files)).json()["documents"][0]["id"]
    r = await client.post(f"/api/documents/{doc_id}/extract")
    assert r.status_code == 409


async def test_extract_missing_document_404(client):
    assert (await client.post("/api/documents/nope/extract")).status_code == 404


async def test_extraction_is_idempotent(client, test_sessionmaker):
    if not DECK.exists():
        pytest.skip("local dataset not present")
    files = {"files": ("deck.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    doc_id = (await client.post("/api/documents/upload", files=files)).json()["documents"][0]["id"]
    await client.post(f"/api/documents/{doc_id}/process")

    await client.post(f"/api/documents/{doc_id}/extract")
    async with test_sessionmaker() as session:
        c1 = (await session.execute(select(func.count()).select_from(Fact).where(Fact.document_id == doc_id))).scalar_one()

    await client.post(f"/api/documents/{doc_id}/extract")
    async with test_sessionmaker() as session:
        c2 = (await session.execute(select(func.count()).select_from(Fact).where(Fact.document_id == doc_id))).scalar_one()

    assert c1 == c2 and c1 > 0