"""Phase 10 — evaluation API: distinct PASS/FAIL/PENDING/NOT_REGISTERED states."""
from __future__ import annotations

import pytest

from app.evaluation.cases import CASES, BY_KEY
from app.services.evaluation import register_cases

OUTCOMES = {"PASS", "FAIL", "PENDING", "NOT_REGISTERED"}


async def _register(client, sessionmaker) -> None:
    async with sessionmaker() as session:
        await register_cases(session, CASES)
        await session.commit()


async def test_results_empty_db_all_not_registered(client):
    r = await client.get("/api/evaluation/results")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == len(CASES)
    assert all(x["outcome"] == "NOT_REGISTERED" for x in results)
    # outcomes are never relationship labels.
    for x in results:
        assert x["outcome"] in OUTCOMES and "UNCERTAIN" not in x["outcome"]


async def test_results_after_registration(client, test_sessionmaker):
    await _register(client, test_sessionmaker)
    r = await client.get("/api/evaluation/results")
    results = r.json()
    by_key = {x["case_key"]: x for x in results}
    # case2 (synthetic fixture) always resolves deterministically in sample mode.
    assert by_key["case2_contradiction"]["outcome"] == "PASS"
    assert by_key["case2_contradiction"]["actual"] == "LIKELY_CONTRADICTION"
    assert by_key["case2_contradiction"]["expected"] == "LIKELY_CONTRADICTION"
    # extracted cases are unresolved in the (empty) test corpus -> NOT_REGISTERED.
    for key in ("case1_corroboration", "case3_resolved", "case4_failure"):
        assert by_key[key]["outcome"] == "NOT_REGISTERED"
    # every result carries its data_mode.
    assert all(x["data_mode"] == "sample" for x in results)


async def test_run_endpoint_sample_only(client, monkeypatch):
    from app.config import settings

    r = await client.post("/api/evaluation/run")
    assert r.status_code == 200
    results = r.json()
    assert len(results) == len(CASES)
    by_key = {x["case_key"]: x for x in results}
    # case2 is a synthetic fixture — deterministic even on an empty corpus.
    assert by_key["case2_contradiction"]["outcome"] == "PASS"
    # extracted cases on an empty corpus have no facts -> PENDING (not FAIL).
    assert by_key["case1_corroboration"]["outcome"] == "PENDING"
    assert by_key["case1_corroboration"]["actual"] is None
    assert by_key["case4_failure"]["outcome"] == "PENDING"

    # A live-llm mode must be refused at the API boundary (script-only path).
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "embedding_provider", "gemini")
    r = await client.post("/api/evaluation/run")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"