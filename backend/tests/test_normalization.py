"""Phase 5 service test: normalize_facts_for_document over the DB."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Document, Fact
from app.services.normalization import normalize_facts_for_document


def _t(y, m, d):
    return datetime(y, m, d, tzinfo=timezone.utc)


@pytest.fixture
async def a_document(test_sessionmaker):
    async with test_sessionmaker() as s:
        doc = Document(filename="a.pdf", stored_path="a.pdf", sha256="x", status="EXTRACTED")
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
        return doc


async def test_normalization_fills_canonical_fields(test_sessionmaker, a_document):
    async with test_sessionmaker() as s:
        s.add(Fact(
            document_id=a_document.id,
            evidence_ids=[],
            entity="Delhivery",
            metric="Revenue",
            raw_value="₹81,415.38 Mn",
            numeric_value=81415.38,
            unit=None,
            value_type="absolute",
            period_raw="FY2024",
            period_type=None,
        ))
        s.add(Fact(
            document_id=a_document.id,
            evidence_ids=[],
            entity="Delhivery",
            metric="Revenue",
            raw_value="₹8,142 Cr",
            numeric_value=8142.0,
            unit=None,
            value_type="absolute",
            period_raw="FY2024",
        ))
        await s.commit()

    async with test_sessionmaker() as s:
        doc = await s.get(Document, a_document.id)
        res = await normalize_facts_for_document(s, doc)
        await s.commit()
        assert res["facts"] == 2
        assert res["changed"]["period"] == 2

    async with test_sessionmaker() as s:
        res = await s.execute(select(Fact).where(Fact.document_id == a_document.id))
        facts = list(res.scalars().all())
        assert len(facts) == 2
        for f in facts:
            assert f.period_type == "fiscal_year"
            assert f.period_start == _t(2023, 4, 1)
            assert f.period_end == _t(2024, 3, 31)
            assert f.fiscal_year_label == "FY2024"
        doc = await s.get(Document, a_document.id)
        assert doc.status == "NORMALIZED"