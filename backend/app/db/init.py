"""Schema creation + lightweight migrations. Idempotent; run at app startup
and via `python -m app.db.init`.

We keep the model authoritative for brand-new databases (``create_all``), and a
tiny ``apply_migrations`` list of ``ADD COLUMN IF NOT EXISTS`` statements for
databases created at earlier milestones (the dev DB predates Phase 10).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import settings
from app.database import engine
from app.models import Base

# Columns added after a database was already created. Run at startup so
# existing dev/test databases get the new observability attributes.
_MIGRATIONS = [
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS data_mode VARCHAR(16) DEFAULT 'sample'",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS provider VARCHAR(32) DEFAULT ''",
]


async def apply_migrations(conn: AsyncConnection) -> None:
    """Idempotent schema upgrades shared by startup and the test harness."""
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await conn.run_sync(Base.metadata.create_all)
    for stmt in _MIGRATIONS:
        await conn.execute(text(stmt))
    await conn.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_facts_embedding_hnsw "
        "ON facts USING hnsw (embedding vector_cosine_ops)"
    ))


async def init_db() -> None:
    """Create pgvector extension (if missing), tables, and the HNSW vector index."""
    async with engine.begin() as conn:
        await apply_migrations(conn)


async def main() -> None:
    if settings.debug:
        print(f"Connecting to {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    await init_db()
    await engine.dispose()
    print("Database schema ready.")


if __name__ == "__main__":
    asyncio.run(main())