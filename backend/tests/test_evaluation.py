"""Phase 9 tests — evaluation harness + the four demo cases.

Pins the 4 required cases to their expected labels by running the real reasoner
over crafted fact pairs, and exercises registration + the /api/evaluation/cases
surface. Mirrors ``app/evaluation/cases.py`` (the single source of truth).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select

from app.evaluation.cases import CASES
from app.llm.adapters.sample import SampleReasoner
from app.models import Document, EvaluationCase, Fact
from app.reasoning import l1
from app.reasoning.engine import decide_pair
from app.services.evaluation import register_cases

FY24 = (datetime(2023, 4, 1, tzinfo=timezone.utc), datetime(2024, 3, 31, tzinfo=timezone.utc))
FY25 = (datetime(2024, 4, 1, tzinfo=timezone.utc), datetime(2025, 3, 31, tzinfo=timezone.utc))
FY26 = (datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2026, 3, 31, tzinfo=timezone.utc))
FY25_9M = (datetime(2024, 4, 1, tzinfo=timezone.utc), datetime(2024, 12, 31, tzinfo=timezone.utc))
FY22 = (datetime(2021, 4, 1, tzinfo=timezone.utc), datetime(2022, 3, 31, tzinfo=timezone.utc))
FY22_9M = (datetime(2021, 4, 1, tzinfo=timezone.utc), datetime(2021, 12, 31, tzinfo=timezone.utc))


def _fact(**kw) -> Fact:
    base = dict(
        id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        entity="Delhivery",
        metric="Total Revenue",
        raw_value="",
        numeric_value=0.0,
        unit="INR million",
        currency="INR",
        value_type="absolute",
        period_raw="FY2024",
        fiscal_year_label="FY2024",
        period_start=FY24[0],
        period_end=FY24[1],
        observation_type="actual",
    )
    base.update(kw)
    return Fact(**base)


class TestCaseVerdicts:
    async def test_case1_corroboration(self, test_sessionmaker):
        fa = _fact(raw_value="₹81,415.38 Mn", numeric_value=81415.38)
        fb = _fact(raw_value="₹8,142 Cr", numeric_value=8142.0, unit="INR crore")
        async with test_sessionmaker() as s:
            d = await decide_pair(s, fa, fb, SampleReasoner())
        assert d is not None
        assert d.label == l1.CORROBORATES
        assert d.confidence > 0.85

    async def test_case2_contradiction_synthetic(self, test_sessionmaker):
        fa = _fact(raw_value="₹91,000 Mn", numeric_value=91000.0,
                   qualifiers={"is_synthetic": True})
        fb = _fact(raw_value="₹81,415.38 Mn", numeric_value=81415.38,
                   qualifiers={"is_synthetic": True})
        async with test_sessionmaker() as s:
            d = await decide_pair(s, fa, fb, SampleReasoner())
        assert d is not None
        assert d.label == l1.LIKELY_CONTRADICTION
        assert d.is_synthetic

    async def test_case3_resolved_gdp_projection(self, test_sessionmaker):
        fa = _fact(entity="India", metric="GDP growth", raw_value="8.2%",
                   numeric_value=8.2, unit="percent", value_type="percent",
                   period_raw="FY2025", fiscal_year_label="FY2025",
                   period_start=FY25[0], period_end=FY25[1], observation_type="actual")
        fb = _fact(entity="India", metric="GDP growth", raw_value="6.2%",
                   numeric_value=6.2, unit="percent", value_type="percent",
                   period_raw="FY2026", fiscal_year_label="FY2026",
                   period_start=FY26[0], period_end=FY26[1], observation_type="projection")
        async with test_sessionmaker() as s:
            d = await decide_pair(s, fa, fb, SampleReasoner())
        assert d is not None
        assert d.label == l1.APPARENT_CONTRADICTION_RESOLVED

    async def test_case4_failure_surfaces_uncertain(self, test_sessionmaker):
        fa = _fact(period_raw="FY2025", fiscal_year_label="FY2025",
                   period_start=FY25[0], period_end=FY25[1], numeric_value=81415.38)
        fb = _fact(period_raw="9M FY2025", fiscal_year_label="FY2025",
                   period_start=FY25_9M[0], period_end=FY25_9M[1],
                   period_type="range", numeric_value=56789.0)
        async with test_sessionmaker() as s:
            d = await decide_pair(s, fa, fb, SampleReasoner())
        assert d is not None
        assert d.label == l1.UNCERTAIN
        assert any("mis-association" in r or "partial" in r for r in d.reasons)


def _corpus_fact(doc_id: str, **kw) -> Fact:
    return _fact(document_id=doc_id, **kw)


class TestRegistration:
    """Registration against a corpus that mirrors the real filenames/facts."""

    async def _corpus(self, test_sessionmaker, client=None) -> dict:
        docs = {}
        async with test_sessionmaker() as s:
            names = {
                "ar.pdf": "02-delhivery-annual-report-fy24-excerpt.pdf",
                "deck.pdf": "03-delhivery-q4-fy24-earnings-presentation.pdf",
                "survey.pdf": "01-india-economic-survey-2024-25-excerpt.pdf",
                "imf.pdf": "03-imf-india-2025-article-iv-excerpt.pdf",
                "prospectus.pdf": "01-delhivery-prospectus-2022-excerpt.pdf",
            }
            for key, filename in names.items():
                doc = Document(filename=filename, stored_path=filename, status="EMBEDDED")
                s.add(doc)
                docs[key] = doc
            await s.flush()

            s.add_all([
                # AR + deck: same revenue, different units -> corroboration
                _corpus_fact(docs["ar.pdf"].id, entity="Delhivery", metric="Total Revenue",
                             raw_value="₹81,415.38 Mn", numeric_value=81415.38, unit="INR million"),
                _corpus_fact(docs["deck.pdf"].id, entity="Delhivery", metric="Total Revenue",
                             raw_value="₹8,142 Cr", numeric_value=8142.0, unit="INR crore"),
                # Survey (FY25 actual) vs IMF (FY26 projection) -> resolved
                _corpus_fact(docs["survey.pdf"].id, entity="India", metric="GDP growth",
                             raw_value="8.2%", numeric_value=8.2, unit="percent",
                             value_type="percent", period_raw="FY2025",
                             fiscal_year_label="FY2025", period_start=FY25[0],
                             period_end=FY25[1], observation_type="actual"),
                _corpus_fact(docs["imf.pdf"].id, entity="India", metric="GDP growth",
                             raw_value="6.2%", numeric_value=6.2, unit="percent",
                             value_type="percent", period_raw="FY2026",
                             fiscal_year_label="FY2026", period_start=FY26[0],
                             period_end=FY26[1], observation_type="projection"),
                # Prospectus: full-year value vs a 9M partial-year value -> UNCERTAIN
                _corpus_fact(docs["prospectus.pdf"].id, metric="Total Revenue",
                             numeric_value=81415.38, period_raw="FY2022",
                             fiscal_year_label="FY2022", period_type="fiscal_year",
                             period_start=FY22[0], period_end=FY22[1]),
                _corpus_fact(docs["prospectus.pdf"].id, metric="Total Revenue",
                             numeric_value=56789.0, period_raw="9M FY2022",
                             fiscal_year_label="FY2022", period_type="range",
                             period_start=FY22_9M[0], period_end=FY22_9M[1]),
            ])
            await s.commit()
        return docs

    async def test_all_four_cases_register(self, test_sessionmaker):
        await self._corpus(test_sessionmaker)
        async with test_sessionmaker() as s:
            results = await register_cases(s, CASES, SampleReasoner())
            await s.commit()
        assert len(results) == 4
        assert all(r["status"] == "registered" for r in results), results
        assert all(r["match"] for r in results), results
        by_key = {r["key"]: r for r in results}
        assert by_key["case1_corroboration"]["actual"] == l1.CORROBORATES
        assert by_key["case2_contradiction"]["actual"] == l1.LIKELY_CONTRADICTION
        assert by_key["case3_resolved"]["actual"] == l1.APPARENT_CONTRADICTION_RESOLVED
        assert by_key["case4_failure"]["actual"] == l1.UNCERTAIN

        async with test_sessionmaker() as s:
            n = (await s.execute(select(func.count()).select_from(EvaluationCase))).scalar_one()
            assert n == 4

    async def test_registration_is_idempotent(self, test_sessionmaker):
        await self._corpus(test_sessionmaker)
        async with test_sessionmaker() as s:
            await register_cases(s, CASES, SampleReasoner())
            await s.commit()
        async with test_sessionmaker() as s:
            again = await register_cases(s, CASES, SampleReasoner())
            await s.commit()
        assert all(r["status"] == "registered" for r in again)

    async def test_cases_api_lists_registered_cases(self, client, test_sessionmaker):
        await self._corpus(test_sessionmaker)
        async with test_sessionmaker() as s:
            await register_cases(s, CASES, SampleReasoner())
            await s.commit()

        r = await client.get("/api/evaluation/cases")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 4
        kinds = {row["kind"] for row in rows}
        assert {"corroboration", "contradiction", "resolved", "failure"} <= kinds
        synthetic = [row for row in rows if row["source"] == "SYNTHETIC_EVALUATION_FIXTURE"]
        assert len(synthetic) == 1
        assert synthetic[0]["kind"] == "contradiction"
        assert synthetic[0]["expected_relationship"] == l1.LIKELY_CONTRADICTION
        assert len(synthetic[0]["fact_ids"]) == 2

        stats = await client.get("/api/stats")
        assert stats.status_code == 200
        assert stats.json()["cases"] == 4