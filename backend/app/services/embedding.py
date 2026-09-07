"""Phase 6 — embeddings for facts (pgvector). Retrieval-only.

Embeds the semantic text of every fact, stores L2-normalised vectors in
``facts.embedding`` (width ``EMBEDDING_DIM``), idempotent. Provider-agnostic via
``factory.get_embedder()`` (Gemini live / deterministic sample).
"""
from __future__ import annotations

import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import EMBEDDING_DIM
from app.llm.factory import get_embedder
from app.models import Document, Fact, ProcessingLog


def fact_text(fact: Fact) -> str:
    """The string we embed — metrics and period talk to each other across docs."""
    parts = [fact.entity, fact.metric]
    if fact.definition:
        parts.append(fact.definition)
    if fact.raw_value:
        parts.append(fact.raw_value)
    if fact.unit:
        parts.append(fact.unit)
    if fact.period_raw:
        parts.append(fact.period_raw)
    elif fact.fiscal_year_label:
        parts.append(fact.fiscal_year_label)
    return " | ".join(parts)


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


async def embed_document(session: AsyncSession, doc: Document, embedder=None) -> dict:
    """Embed all facts of a document. Idempotent (overwrites embeddings)."""
    embedder = embedder or get_embedder()
    res = await session.execute(select(Fact).where(Fact.document_id == doc.id))
    facts = list(res.scalars().all())
    if not facts:
        raise RuntimeError(f"Document {doc.filename} has no facts to embed")

    texts = [fact_text(f) for f in facts]
    vectors: list[list[float]] = []
    for i in range(0, len(texts), embedder.batch_size):
        vectors.extend(await embedder.embed(texts[i : i + embedder.batch_size]))

    if len(vectors) != len(facts):
        raise RuntimeError(f"embedder returned {len(vectors)} vectors for {len(facts)} facts")
    for fact, vec in zip(facts, vectors):
        if len(vec) != EMBEDDING_DIM:
            raise RuntimeError(f"expected {EMBEDDING_DIM} dims, got {len(vec)}")
        fact.embedding = l2_normalize(vec)
        session.add(fact)

    doc.status = "EMBEDDED"
    session.add(ProcessingLog(
        document_id=doc.id,
        stage="embed",
        message=f"embedded {len(facts)} facts ({embedder.name})",
        meta_json={"facts": len(facts), "embedder": embedder.name, "dim": EMBEDDING_DIM},
    ))
    return {"facts": len(facts), "embedder": embedder.name, "dim": EMBEDDING_DIM}