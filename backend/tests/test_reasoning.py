"""Phase 8 tests: L1 arithmetic verdicts, L3 fusion (with L2 judge), pipeline, API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.llm.adapters.sample import SampleReasoner
from app.models import Document, Evidence, Fact, Relationship
from app.reasoning import l1
from app.reasoning.engine import decide_pair
from app.services.reasoning import run_relationships_for_document

FY24 = (datetime(2023, 4, 1, tzinfo=timezone.utc), datetime(2024, 3, 31, tzinfo=timezone.utc))
FY23 = (datetime(2022, 4, 1, tzinfo=timezone.utc), datetime(2023, 3, 31, tzinfo=timezone.utc))


def _fact(**kw) -> Fact:
    base = dict(
        id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        entity="Delhivery",
        metric="Total Revenue",
        raw_value="",
        numeric_value=0.0,
        unit="",
        currency="",
        value_type="absolute",
        period_raw="FY2024",
        fiscal_year_label="FY2024",
        period_start=FY24[0],
        period_end=FY24[1],
        observation_type="actual",
    )
    base.update(kw)
    return Fact(**base)


def fy24_ar() -> Fact:
    return _fact(raw_value="₹81,415.38 Mn", numeric_value=81415.38,
                 unit="INR million", currency="INR")


def fy24_deck() -> Fact:
    return _fact(raw_value="₹8,142 Cr", numeric_value=8142.0,
                 unit="INR crore", currency="INR")


class TestL1Arithmetic:
    def test_corroborates_across_units(self):
        v = l1.reason_pair(fy24_ar(), fy24_deck())
        assert v.comparable
        assert v.label == l1.CORROBORATES
        assert v.strength == l1.STRONG
        assert v.confidence > 0.85
        assert any("within tolerance" in r for r in v.reasons)

    def test_contradiction_same_period_both_actual(self):
        a = _fact(numeric_value=1000.0, unit="INR million", currency="INR")
        b = _fact(numeric_value=2000.0, unit="INR million", currency="INR")
        v = l1.reason_pair(a, b)
        assert v.label == l1.LIKELY_CONTRADICTION
        assert v.strength == l1.STRONG

    def test_resolved_different_periods(self):
        a = _fact(metric="EBITDA", raw_value="₹1,266 Mn", numeric_value=1266.0,
                  unit="INR million", currency="INR")
        b = _fact(metric="EBITDA", raw_value="−₹4,516 Mn", numeric_value=-4516.0,
                  unit="INR million", currency="INR", period_raw="FY2023",
                  fiscal_year_label="FY2023", period_start=FY23[0], period_end=FY23[1])
        v = l1.reason_pair(a, b)
        assert v.label == l1.APPARENT_CONTRADICTION_RESOLVED
        assert v.strength == l1.STRONG

    def test_percent_corroborates(self):
        a = _fact(metric="GDP growth", raw_value="8.2%", numeric_value=8.2,
                  unit="percent", value_type="percent", entity="India", period_raw="FY2025",
                  fiscal_year_label="FY2025")
        b = _fact(metric="GDP growth", raw_value="8.2%", numeric_value=8.2,
                  unit="percent", value_type="percent", entity="India", period_raw="FY2025",
                  fiscal_year_label="FY2025")
        v = l1.reason_pair(a, b)
        assert v.label == l1.CORROBORATES
        assert v.strength == l1.STRONG

    def test_unrelated_pairs_not_comparable(self):
        rev = fy24_ar()
        gdp = _fact(metric="GDP growth", raw_value="8.2%", numeric_value=8.2,
                    unit="percent", value_type="percent", entity="India")
        v = l1.reason_pair(rev, gdp)
        assert not v.comparable
        assert v.label == l1.UNCERTAIN

    def test_mixed_value_types_weak_but_comparable(self):
        a = _fact(metric="EBITDA margin", numeric_value=18.0, unit="percent",
                  value_type="percent")
        b = _fact(metric="EBITDA margin", numeric_value=1266.0, unit="INR million",
                  currency="INR", value_type="absolute")
        v = l1.reason_pair(a, b)
        assert v.comparable
        assert v.strength == l1.WEAK

    def test_nonactual_vs_actual_overlapping_is_weak(self):
        a = _fact(numeric_value=81000.0, unit="INR million", currency="INR", observation_type="actual")
        b = _fact(numeric_value=85000.0, unit="INR million", currency="INR", observation_type="projection")
        v = l1.reason_pair(a, b)
        assert v.label == l1.APPARENT_CONTRADICTION_RESOLVED
        assert v.strength == l1.WEAK


class TestDecisionFusion:
    async def test_strong_verdict_needs_no_l2(self, test_sessionmaker):
        async with test_sessionmaker() as s:
            d = await decide_pair(s, fy24_ar(), fy24_deck(), SampleReasoner())
        assert d is not None
        assert d.label == l1.CORROBORATES
        assert not d.l2_used

    async def test_weak_verdict_runs_l2_and_upgrades(self, test_sessionmaker):
        async with test_sessionmaker() as s:
            a = _fact(numeric_value=81000.0, unit="INR million", currency="INR", observation_type="actual")
            b = _fact(numeric_value=85000.0, unit="INR million", currency="INR", observation_type="projection")
            d = await decide_pair(s, a, b, SampleReasoner(), allow_l2=True)
        assert d.l2_used
        assert d.llm_reasoning
        assert any("L2" in r for r in d.reasons)

    async def test_unrelated_pair_gives_none(self, test_sessionmaker):
        async with test_sessionmaker() as s:
            d = await decide_pair(s, fy24_ar(),
                                  _fact(metric="GDP growth", numeric_value=8.2,
                                        unit="percent", value_type="percent", entity="India"),
                                  SampleReasoner())
        assert d is None


class TestDocumentPipeline:
    async def _two_docs(self, test_sessionmaker):
        docs = {}
        async with test_sessionmaker() as s:
            ar = Document(filename="ar.pdf", stored_path="ar.pdf", status="EMBEDDED")
            deck = Document(filename="deck.pdf", stored_path="deck.pdf", status="EMBEDDED")
            s.add_all([ar, deck])
            await s.flush()
            ar_fact = Fact(document_id=ar.id, entity="Delhivery", metric="Total Revenue",
                           raw_value="₹81,415.38 Mn", numeric_value=81415.38,
                           unit="INR million", currency="INR", value_type="absolute",
                           period_raw="FY2024", fiscal_year_label="FY2024",
                           period_start=FY24[0], period_end=FY24[1], observation_type="actual")
            deck_fact = Fact(document_id=deck.id, entity="Delhivery", metric="Total Revenue",
                             raw_value="₹8,142 Cr", numeric_value=8142.0,
                             unit="INR crore", currency="INR", value_type="absolute",
                             period_raw="FY2024", fiscal_year_label="FY2024",
                             period_start=FY24[0], period_end=FY24[1], observation_type="actual")
            s.add_all([ar_fact, deck_fact])
            await s.commit()
            docs["ar"] = ar
            docs["deck"] = deck
        return docs

    async def test_pipeline_stores_corroboration_and_is_idempotent(self, test_sessionmaker):
        docs = await self._two_docs(test_sessionmaker)
        async with test_sessionmaker() as s:
            ar = await s.get(Document, docs["ar"].id)
            first = await run_relationships_for_document(s, ar)
            await s.commit()
        assert first["stored"] >= 1
        assert first["labels"].get(l1.CORROBORATES, 0) >= 1

        async with test_sessionmaker() as s:
            ar = await s.get(Document, docs["ar"].id)
            second = await run_relationships_for_document(s, ar)
            await s.commit()
        assert second["stored"] == 0  # idempotent — nothing new to add

        async with test_sessionmaker() as s:
            stmt = select(Relationship).where(Relationship.relationship_type == l1.CORROBORATES)
            rels = (await s.execute(stmt)).scalars().all()
            assert rels
            rel = rels[0]
            assert rel.confidence > 0.8
            assert rel.reasons

    async def test_user_facing_document_status(self, test_sessionmaker):
        docs = await self._two_docs(test_sessionmaker)
        async with test_sessionmaker() as s:
            ar = await s.get(Document, docs["ar"].id)
            await run_relationships_for_document(s, ar)
            doc = await s.get(Document, docs["ar"].id)
            assert doc.status == "REASONED"


class TestRelationshipApi:
    async def test_reason_endpoint_and_relationships(self, client, test_sessionmaker):
        async with test_sessionmaker() as s:
            ar = Document(filename="ar.pdf", stored_path="ar.pdf", status="EMBEDDED")
            deck = Document(filename="deck.pdf", stored_path="deck.pdf", status="EMBEDDED")
            s.add_all([ar, deck])
            await s.flush()
            e1 = Evidence(document_id=ar.id, page_number=42, block_index=0, content="Total Revenue ₹81,415.38 Mn for FY24")
            s.add(e1)
            await s.flush()
            s.add_all([
                Fact(document_id=ar.id, evidence_ids=[e1.id], entity="Delhivery", metric="Total Revenue",
                     raw_value="₹81,415.38 Mn", numeric_value=81415.38, unit="INR million",
                     currency="INR", value_type="absolute", period_raw="FY2024",
                     fiscal_year_label="FY2024", period_start=FY24[0], period_end=FY24[1],
                     observation_type="actual"),
                Fact(document_id=deck.id, evidence_ids=[], entity="Delhivery", metric="Total Revenue",
                     raw_value="₹8,142 Cr", numeric_value=8142.0, unit="INR crore",
                     currency="INR", value_type="absolute", period_raw="FY2024",
                     fiscal_year_label="FY2024", period_start=FY24[0], period_end=FY24[1],
                     observation_type="actual"),
            ])
            await s.commit()
            ar_id = ar.id

        r = await client.post(f"/api/documents/{ar_id}/reason")
        assert r.status_code == 200
        assert r.json()["status"] == "REASONED"

        r = await client.get("/api/relationships?relationship_type=CORROBORATES")
        assert r.status_code == 200
        rows = r.json()
        assert rows, "expected at least one CORROBORATES relationship"
        assert all(row["relationship_type"] == "CORROBORATES" for row in rows)
        # detail view carries both facts
        rel_id = rows[0]["id"]
        detail = await client.get(f"/api/relationships/{rel_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["fact_a"]["metric"] == "Total Revenue"

    async def test_reason_409_when_not_ready(self, client, test_sessionmaker):
        async with test_sessionmaker() as s:
            doc = Document(filename="x.pdf", stored_path="x.pdf", status="UPLOADED")
            s.add(doc)
            await s.commit()
            doc_id = doc.id
        r = await client.post(f"/api/documents/{doc_id}/reason")
        assert r.status_code == 409