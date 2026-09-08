"""LLM provider abstraction.

Adapters implement the ``FactExtractor`` protocol (and, in later phases,
``RelationshipReasoner`` / ``Embedder``). The pipeline never talks to a
provider SDK directly — it always goes through ``factory.get_extractor()``.

Swapping providers (Gemini ↔ OpenAI ↔ sample, etc.) is a .env change only.
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class EvidenceBlockSpec(BaseModel):
    """A single evidence block handed to the extractor."""
    index: int
    page_number: int
    evidence_type: str
    content: str


class ExtractedFact(BaseModel):
    """Structured fact as produced by an extractor (before DB validation)."""
    entity: str = "unknown"
    metric: str = ""
    definition: str = ""
    raw_value: str = ""
    numeric_value: float | None = None
    unit: str = ""
    currency: str = ""
    value_type: str = "absolute"
    period_raw: str = ""
    period_type: str = "unknown"
    fiscal_year_label: str = ""
    observation_type: str = "unknown"
    scope: str = ""
    geography: str = ""
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5
    source_block_indices: list[int] = Field(default_factory=list)


class ExtractionResponse(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)


class FactExtractor(Protocol):
    """Turns evidence blocks into extraction candidates."""

    name: str

    async def extract(self, blocks: list[EvidenceBlockSpec]) -> list[ExtractedFact]:
        ...

    @staticmethod
    def extractable(blocks: list[EvidenceBlockSpec]) -> list[EvidenceBlockSpec]:
        """Blocks worth sending to an LLM (numeric candidates)."""
        from app.processing.parse import has_number

        return [b for b in blocks if b.evidence_type == "table" or has_number(b.content)]


# Fixed vector width for the `facts.embedding` column (pgvector Vector(N)).
# gemini-embedding-001 emits 3072 by default but we pin a reduced dimension
# (Matryoshka) so an HNSW index is allowed (pgvector caps spatial indexes at
# 2000 dims); sample mode must match whatever is configured.
from app.config import settings

EMBEDDING_DIM = settings.embedding_dim


class Embedder(Protocol):
    """Turns fact text into embedding vectors of width EMBEDDING_DIM."""

    name: str

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...


class ReasonedConclusion(BaseModel):
    """L2 judge verdict for a single fact pair."""
    label: str = "UNCERTAIN"  # one of the four relationship labels
    confidence: float = 0.5
    rationale: str = ""
    is_synthetic: bool = False


class RelationshipReasoner(Protocol):
    """Judges one fact pair against the relationship labels."""

    name: str

    async def reason(self, fact_a: dict, fact_b: dict) -> ReasonedConclusion:
        ...


class LLMProvider(Protocol):
    """Unified LLM backing for extraction and L2 reasoning.

    Concrete: ``GeminiProvider``, ``OllamaProvider``, ``SampleProvider``.
    Chosen via ``LLM_PROVIDER`` env; the pipeline only ever sees this protocol.
    """

    name: str

    async def extract(self, blocks: list[EvidenceBlockSpec]) -> list[ExtractedFact]:
        ...

    async def reason(self, fact_a: dict, fact_b: dict) -> ReasonedConclusion:
        ...


class EmbeddingProvider(Protocol):
    """Text embedding backing (``facts.embedding`` of width ``EMBEDDING_DIM``).

    Concrete: ``GeminiEmbeddingProvider``, ``LocalEmbeddingProvider``,
    ``SampleEmbedder``. Chosen via ``EMBEDDING_PROVIDER`` env.
    """

    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]:
        ...