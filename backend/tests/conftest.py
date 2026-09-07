"""Shared test fixtures.

Strategy: run tests against a dedicated ``factknowledge_test`` database on the
same Dockerized Postgres instance. We build the schema once per session and
truncate tables between tests for isolation. The app's ``get_db`` dependency is
overridden with a session bound to the test engine.

NullPool avoids cross-event-loop connection reuse issues with pytest-asyncio.
"""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.main import app

TEST_DB = f"{settings.postgres_db}_test"

TEST_URL = (
    f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}"
    f"@{settings.postgres_host}:{settings.postgres_port}/{TEST_DB}"
)


@pytest.fixture(scope="session")
async def test_engine():
    # Create the test database if missing (connect to the maintenance DB).
    admin = create_async_engine(TEST_URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT", poolclass=NullPool)
    async with admin.connect() as conn:
        exists = await conn.scalar(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": TEST_DB})
        if not exists:
            await conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    await admin.dispose()

    engine = create_async_engine(TEST_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        from app.models import Base
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_db(test_engine):
    async with test_engine.begin() as conn:
        for table in ("relationships", "facts", "evidence", "evaluation_cases", "documents", "processing_logs"):
            await conn.execute(text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def use_sample_provider(monkeypatch):
    """Tests never touch a live LLM provider; force the deterministic sample extractor."""
    monkeypatch.setattr(settings, "llm_provider", "sample")


@pytest.fixture
def test_sessionmaker(test_engine):
    return async_sessionmaker(test_engine, expire_on_commit=False)


@pytest.fixture
async def client(test_sessionmaker):
    """HTTP client against the app with get_db overridden to the test DB."""
    from app.database import get_db

    async def _override():
        async with test_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = _override

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()