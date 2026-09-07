"""Phase 7 tests: hybrid candidate retrieval across documents."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Document, Fact
from app.retrieval import metric_tokens, retrieve_candidates, structural_sim
from app.services.embedding import embed_document


@pytest.fixture
async def corpus(test_sessionmaker):
    """Three documents: two share Delhivery Revenue FY2024, one is unrelated GDP."""
    async with test_sessionmaker() as s:
        docs = {}
        for name in ("ar.pdf", "deck.pdf", "gdp.pdf"):
            doc = Document(filename=name, stored_path=name, sha256=name, status="NORMALIZED")
            s.add(doc)
            await s.flush()
            docs[name] = doc
            facts = []
            if name.startswith("revenue") or name in ("ar.pdf", "deck.pdf"):
                facts.append(Fact(document_id=doc.id, evidence_ids=[], entity="Delhivery",
                                  metric="Total Revenue", raw_value="₹81,415.38 Mn",
                                  numeric_value=81415.38, unit="INR million", currency="INR",
                                  value_type="absolute", period_raw="FY2024",
                                  fiscal_year_label="FY2024", observation_type="actual"))
                facts.append(Fact(document_id=doc.id, evidence_ids=[], entity="Delhivery",
                                  metric="Total Revenue", raw_value="₹8,142 Cr",
                                  numeric_value=8142.0, unit="INR crore", currency="INR",
                                  value_type="absolute", period_raw="FY2024",
                                  fiscal_year_label="FY2024", observation_type="actual"))
            if name == "gdp.pdf":
                facts.append(Fact(document_id=doc.id, evidence_ids=[], entity="India",
                                  metric="GDP growth", raw_value="8.2%", numeric_value=8.2,
                                  unit="percent", value_type="percent", period_raw="FY2025",
                                  fiscal_year_label="FY2025", observation_type="actual"))
            s.add_all(facts)
        await s.commit()
        return docs


async def _embed_all(test_sessionmaker, docs):
    async with test_sessionmaker() as s:
        for d in docs.values():
            await embed_document(s, d)
        await s.commit()


async def _facts_of(session, doc) -> list[Fact]:
    res = await session.execute(select(Fact).where(Fact.document_id == doc.id))
    return list(res.scalars().all())


class TestHybridRanking:
    async def test_same_metric_cross_doc_ranks_first(self, test_sessionmaker, corpus):
        await _embed_all(test_sessionmaker, corpus)
        async with test_sessionmaker() as s:
            rev_a = (await _facts_of(s, corpus["ar.pdf"]))[0]  # Revenue 81,415.38 Mn
            rev_b = (await _facts_of(s, corpus["deck.pdf"]))[0]  # Revenue 8,142 Cr
            cands = await retrieve_candidates(s, rev_a, limit=10)

            assert cands, "expected at least one candidate"
            top = cands[0]
            assert top.fact.document_id == corpus["deck.pdf"].id  # corroborating doc ranks first
            assert top.fact.metric == "Total Revenue"
            assert top.fact.document_id != rev_a.document_id

    async def test_gdp_is_not_pulled_in_as_top_candidate(self, test_sessionmaker, corpus):
        await _embed_all(test_sessionmaker, corpus)
        async with test_sessionmaker() as s:
            rev_a = (await _facts_of(s, corpus["ar.pdf"]))[0]
            cands = await retrieve_candidates(s, rev_a, limit=10)
            gdp_facts = await _facts_of(s, corpus["gdp.pdf"])
            assert all(c.fact.id != gdp_facts[0].id for c in cands[:2])

    async def test_same_document_excluded(self, test_sessionmaker, corpus):
        await _embed_all(test_sessionmaker, corpus)
        async with test_sessionmaker() as s:
            rev_a = (await _facts_of(s, corpus["ar.pdf"]))[0]
            other = (await _facts_of(s, corpus["ar.pdf"]))[1]  # same doc, same metric
            cands = await retrieve_candidates(s, rev_a, limit=10)
            assert all(c.fact.id != other.id for c in cands)

    async def test_period_overlap_boosts(self):
        from datetime import datetime, timezone

        t0 = datetime(2023, 4, 1, tzinfo=timezone.utc)
        t1 = datetime(2024, 3, 31, tzinfo=timezone.utc)
        a = Fact(metric="Total Revenue", entity="Delhivery", fiscal_year_label="FY2024",
                 period_start=t0, period_end=t1, unit="INR million", value_type="absolute")
        b = Fact(metric="Total Revenue", entity="Delhivery", fiscal_year_label="FY2024",
                 period_start=t0, period_end=t1, unit="INR crore", value_type="absolute")
        score, breakdown = structural_sim(a, b)
        assert score > 0.8
        assert breakdown["period_overlap"] == 1.0


class TestApi:
    async def test_candidates_endpoint(self, test_sessionmaker, client, corpus):
        await _embed_all(test_sessionmaker, corpus)
        async with test_sessionmaker() as s:
            rev_a = (await _facts_of(s, corpus["ar.pdf"]))[0]
            fact_id = rev_a.id
        resp = await client.get(f"/api/facts/{fact_id}/candidates?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data, "expected candidates"
        assert "hybrid_score" in data[0]
        assert "cosine_sim" in data[0]

    async def test_malformed_id(self, client):
        resp = await client.get("/api/facts/none/candidates")
        assert resp.status_code == 404


class TestMetricTokens:
    def test_stopwords_removed(self):
        assert metric_tokens("YoY % change in revenue") == {"change", "revenue"}