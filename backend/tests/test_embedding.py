"""Phase 6 tests: embeddings + pgvector indexing."""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.adapters.sample import SampleEmbedder
from app.models import Document, Fact
from app.services.embedding import embed_document, fact_text, l2_normalize


@pytest.fixture
async def a_document(test_sessionmaker) -> Fact:
    async with test_sessionmaker() as s:
        doc = Document(filename="a.pdf", stored_path="a.pdf", sha256="x", status="NORMALIZED")
        s.add(doc)
        await s.commit()
        await s.refresh(doc)
        f = Fact(document_id=doc.id, evidence_ids=[], entity="Delhivery",
                 metric="Revenue", raw_value="₹8,142 Cr", unit="INR crore",
                 value_type="absolute", period_raw="FY2024", numeric_value=8142.0,
                 observation_type="actual")
        s.add(f)
        await s.commit()
        return f


class TestSampleEmbedder:
    async def test_dim(self):
        emb = await SampleEmbedder().embed(["Delhivery Revenue"])
        assert len(emb[0]) == 1536

    async def test_similar_text_nearby(self):
        e = SampleEmbedder()
        a, b, c = await e.embed(["Delhivery revenue FY2024", "Delhivery revenue FY2024", "GDP growth 2025"])
        dot_ab = sum(x * y for x, y in zip(a, b))
        dot_ac = sum(x * y for x, y in zip(a, c))
        assert dot_ab > 0.99
        assert dot_ab > dot_ac

    async def test_deterministic(self):
        e = SampleEmbedder()
        a = await e.embed(["Revenue of Delhivery in crore"])
        b = await e.embed(["Revenue of Delhivery in crore"])
        assert a[0] == b[0]


class TestEmbedService:
    async def test_embed_document(self, test_sessionmaker, a_document: Fact):
        async with test_sessionmaker() as s:
            doc = await s.get(Document, a_document.document_id)
            res = await embed_document(s, doc)
            await s.commit()
            assert res["facts"] == 1
            assert res["dim"] == 1536

        async with test_sessionmaker() as s:
            f = await s.get(Fact, a_document.id)
            assert f.embedding is not None
            assert len(f.embedding) == 1536
            assert sum(v * v for v in f.embedding) == pytest.approx(1.0)
            doc = await s.get(Document, a_document.document_id)
            assert doc.status == "EMBEDDED"

    async def test_idempotent_rerun(self, test_sessionmaker, a_document: Fact):
        async with test_sessionmaker() as s:
            doc = await s.get(Document, a_document.document_id)
            await embed_document(s, doc)
            await s.commit()
        async with test_sessionmaker() as s:
            doc = await s.get(Document, a_document.document_id)
            res = await embed_document(s, doc)
            await s.commit()
            assert res["facts"] == 1

    async def test_cosine_retrieval_via_sql(self, test_sessionmaker):
        """Two same-metric facts across docs should rank above an unrelated one."""
        async with test_sessionmaker() as s:
            for name in ("revenue-a.pdf", "revenue-b.pdf", "gdp.pdf"):
                doc = Document(filename=name, stored_path=name, sha256=name, status="NORMALIZED")
                s.add(doc)
                await s.flush()
                metric = "Revenue" if name.startswith("revenue") else "GDP growth"
                s.add(Fact(document_id=doc.id, evidence_ids=[], entity="Co", metric=metric,
                           raw_value="1,000", unit="INR crore", value_type="absolute",
                           period_raw="FY2024", numeric_value=1000.0))
            await s.commit()

        async with test_sessionmaker() as s:
            docs = (await s.execute(text("SELECT id FROM documents"))).scalars().all()
            for d in docs:
                doc = await s.get(Document, d)
                await embed_document(s, doc)
            await s.commit()

        async with test_sessionmaker() as s:
            res = await s.execute(text("""
                SELECT a.metric AS m1, b.metric AS m2,
                       1 - (a.embedding <=> b.embedding) AS sim
                FROM facts a, facts b
                WHERE a.id < b.id
                ORDER BY sim DESC
            """))
            pairs = res.all()
            assert pairs[0].m1 == pairs[0].m2  # nearest pair shares the metric
            assert pairs[0].sim > pairs[-1].sim


class TestFactText:
    def test_includes_metric_and_period(self):
        f = Fact(entity="Delhivery", metric="Revenue", raw_value="8,142", unit="INR crore",
                 period_raw="FY2024")
        assert "Revenue" in fact_text(f)
        assert "FY2024" in fact_text(f)
        assert "INR crore" in fact_text(f)