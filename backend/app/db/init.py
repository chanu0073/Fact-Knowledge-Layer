"""Schema creation. Idempotent; run at app startup and via `python -m app.db.init`."""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.models import Base


async def init_db() -> None:
    """Create pgvector extension (if missing), tables, and the HNSW vector index."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        # HNSW approximate NN index over fact embeddings (cosine). Requires pgvector >= 0.5.
        await conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_facts_embedding_hnsw "
            "ON facts USING hnsw (embedding vector_cosine_ops)"
        ))


async def main() -> None:
    if settings.debug:
        print(f"Connecting to {settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}")
    await init_db()
    await engine.dispose()
    print("Database schema ready.")


if __name__ == "__main__":
    asyncio.run(main())