"""SQLAlchemy declarative models for the Fact Knowledge Layer.

Data model design (explainable in interview):

- ``documents``   - uploaded PDF metadata + processing status.
- ``evidence``    - granular, provenance-carrying source records (page + block + type + content).
                   Every fact references one or more evidence rows -> evidence grounding.
- ``facts``       - normalized, structured facts. Flexible attributes live in ``qualifiers`` (JSONB)
                   so new fact types never require a schema migration. ``embedding`` is a pgvector
                   column used ONLY for candidate retrieval, never for relationship decisions.
- ``relationships`` - pairwise fact comparisons with a label, confidence and structured reasoning.
- ``evaluation_cases`` - records backing the four demo cases. Synthetic fixtures are labelled.
- ``processing_logs`` - observability of pipeline runs.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    Index,
    event,
)

from app.llm.base import EMBEDDING_DIM
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(512))
    stored_path: Mapped[str] = mapped_column(String(1024), default="")
    sha256: Mapped[str] = mapped_column(String(64), default="")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="UPLOADED")
    error_message: Mapped[str] = mapped_column(Text, default="")
    # Data provenance/mode: which extractor/embedder produced this document's
    # facts. sample | live-llm | fixture — never conflated in the UI/stats.
    data_mode: Mapped[str] = mapped_column(String(16), default="sample")
    provider: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<Document {self.filename} status={self.status}>"


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_doc_page", "document_id", "page_number"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    block_index: Mapped[int] = mapped_column(Integer, default=0)
    evidence_type: Mapped[str] = mapped_column(String(16), default="text")  # text | table
    content: Mapped[str] = mapped_column(Text)
    location_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    def __repr__(self) -> str:
        return f"<Evidence doc={self.document_id} p={self.page_number} type={self.evidence_type}>"


class Fact(Base):
    __tablename__ = "facts"
    __table_args__ = (
        Index("ix_facts_document", "document_id"),
        Index("ix_facts_entity", "entity"),
        Index("ix_facts_metric", "metric"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"))
    evidence_ids: Mapped[list] = mapped_column(JSONB, default=list)

    # Core semantic envelope
    entity: Mapped[str] = mapped_column(String(512), default="")
    metric: Mapped[str] = mapped_column(String(512), default="")
    definition: Mapped[str] = mapped_column(Text, default="")
    raw_value: Mapped[str] = mapped_column(String(256), default="")
    numeric_value: Mapped[float] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(64), default="")
    currency: Mapped[str] = mapped_column(String(16), default="")
    value_type: Mapped[str] = mapped_column(String(24), default="absolute")  # absolute|percent|ratio|quantity|date|categorical|boolean

    # Temporal model
    period_raw: Mapped[str] = mapped_column(String(128), default="")
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    period_type: Mapped[str] = mapped_column(String(24), default="unknown")  # fiscal_year|quarter|month|date|range|unknown
    fiscal_year_label: Mapped[str] = mapped_column(String(24), default="")  # e.g. "FY2024" for grouping

    # Context
    observation_type: Mapped[str] = mapped_column(String(24), default="unknown")  # actual|estimate|forecast|projection|guidance|historical|unknown
    scope: Mapped[str] = mapped_column(String(64), default="")
    geography: Mapped[str] = mapped_column(String(64), default="")
    qualifiers: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Extraction metadata
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    raw_extraction_json: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Embedding (pgvector). Retrieval-only.
    embedding: Mapped[list] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def __repr__(self) -> str:
        return f"<Fact {self.entity} {self.metric} {self.raw_value} {self.period_raw}>"


# Free-form extractor strings must never exceed column widths, no matter which
# path created the object (live/sample extraction, fixtures, scripts).
_FACT_LENGTH_LIMITS = {"entity": 512, "metric": 512, "raw_value": 256, "unit": 64,
                       "currency": 16, "period_raw": 128, "observation_type": 24,
                       "value_type": 24, "scope": 64, "geography": 64,
                       "fiscal_year_label": 24}


def _clamp_fact_lengths(_mapper, _connection, target: Fact) -> None:
    for attr, limit in _FACT_LENGTH_LIMITS.items():
        value = getattr(target, attr, None)
        if isinstance(value, str) and len(value) > limit:
            setattr(target, attr, value[:limit])


event.listen(Fact, "before_insert", _clamp_fact_lengths)
event.listen(Fact, "before_update", _clamp_fact_lengths)


class Relationship(Base):
    __tablename__ = "relationships"
    __table_args__ = (
        Index("ix_rel_fact_a", "fact_a_id"),
        Index("ix_rel_fact_b", "fact_b_id"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    fact_a_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("facts.id", ondelete="CASCADE"))
    fact_b_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("facts.id", ondelete="CASCADE"))
    relationship_type: Mapped[str] = mapped_column(String(40))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    evidence_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    llm_reasoning: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    def __repr__(self) -> str:
        return f"<Relationship {self.relationship_type}>"


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    kind: Mapped[str] = mapped_column(String(24))  # corroboration|contradiction|resolved|failure
    source: Mapped[str] = mapped_column(String(40), default="extracted")  # extracted | SYNTHETIC_EVALUATION_FIXTURE
    title: Mapped[str] = mapped_column(String(256), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    relationship_id: Mapped[str] = mapped_column(String(64), nullable=True)
    fact_ids: Mapped[list] = mapped_column(JSONB, default=list)
    expected_relationship: Mapped[str] = mapped_column(String(40), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ProcessingLog(Base):
    __tablename__ = "processing_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(String(64), nullable=True)
    stage: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text, default="")
    meta_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)