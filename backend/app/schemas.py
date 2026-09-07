from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthOut(BaseModel):
    status: str
    app: str
    version: str
    db_ok: bool
    provider: str


class DocumentOut(ORMModel):
    id: str
    filename: str
    page_count: int
    status: str
    error_message: str = ""
    created_at: datetime
    updated_at: Optional[datetime] = None
    sha256: str = ""


class UploadOut(BaseModel):
    documents: list[DocumentOut]


class EvidenceOut(BaseModel):
    id: str
    document_id: str
    page_number: int
    block_index: int
    evidence_type: str
    content: str


class FactOut(ORMModel):
    id: str
    document_id: str
    evidence_ids: list[str] = []
    entity: str
    metric: str
    definition: str = ""
    raw_value: str = ""
    numeric_value: Optional[float] = None
    unit: str = ""
    currency: str = ""
    value_type: str = ""
    period_raw: str = ""
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    period_type: str = ""
    fiscal_year_label: str = ""
    observation_type: str = ""
    scope: str = ""
    geography: str = ""
    qualifiers: dict[str, Any] = {}
    extraction_confidence: float = 0.0
    created_at: datetime


class FactDetailOut(FactOut):
    document_filename: str = ""
    evidence: list[EvidenceOut] = []
    relationships: list["RelationshipOut"] = []


class RelationshipOut(ORMModel):
    id: str
    fact_a_id: str
    fact_b_id: str
    relationship_type: str
    confidence: float
    reasons: list[Any] = []
    llm_reasoning: str = ""
    is_synthetic: bool = False
    created_at: datetime


class RelationshipDetailOut(RelationshipOut):
    fact_a: Optional[FactOut] = None
    fact_b: Optional[FactOut] = None


class EvaluationCaseOut(BaseModel):
    id: str
    kind: str
    source: str
    title: str = ""
    description: str = ""
    explanation: str = ""
    relationship_id: Optional[str] = None
    fact_ids: list[str] = []
    expected_relationship: str = ""


class StatsOut(BaseModel):
    documents: int
    facts: int
    evidence: int
    relationships: dict[str, int]
    provider: str


FactDetailOut.model_rebuild()
RelationshipDetailOut.model_rebuild()