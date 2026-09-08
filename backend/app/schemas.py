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
    # Observability: which mode/provider produced this document's facts.
    data_mode: str = "sample"
    provider: str = ""
    created_at: datetime
    updated_at: Optional[datetime] = None
    sha256: str = ""


class UploadOut(BaseModel):
    documents: list[DocumentOut]


class PipelineQueuedOut(BaseModel):
    """202 response from the aggregate pipeline endpoint."""
    queued: bool = True
    document: DocumentOut
    note: str = ""


class EvidenceOut(ORMModel):
    id: str
    document_id: str
    page_number: int
    block_index: int
    evidence_type: str
    content: str
    location_json: dict[str, Any] = {}


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
    # Provenance enrichment (populated on list/detail responses, defaults
    # elsewhere so relationship-embedded facts stay compact).
    document_filename: str = ""
    page_number: Optional[int] = None
    grounding: str = ""


class FactDetailOut(FactOut):
    document_filename: str = ""
    evidence: list[EvidenceOut] = []
    relationships: list["RelationshipOut"] = []


class CandidateOut(FactOut):
    grounding: str = ""
    cosine_sim: Optional[float] = None
    structural_sim: float = 0.0
    hybrid_score: float = 0.0
    source: str = ""
    breakdown: dict[str, Any] = {}


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


class RelationshipFactOut(FactOut):
    """Fact as embedded in a relationship detail — with its own evidence so the
    doc → page → block → fact → verdict trace is self-contained."""
    document_filename: str = ""
    evidence: list[EvidenceOut] = []


class RelationshipDetailOut(RelationshipOut):
    fact_a: Optional[RelationshipFactOut] = None
    fact_b: Optional[RelationshipFactOut] = None


class ProcessingLogOut(BaseModel):
    id: str
    document_id: Optional[str] = None
    stage: str
    message: str = ""
    meta_json: dict[str, Any] = {}
    created_at: datetime


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


class EvaluationResultOut(BaseModel):
    """Per-case evaluation outcome. Outcome is deliberately NOT a relationship
    label: PASS/FAIL/PENDING/NOT_REGISTERED describe the *case*, while ``actual``
    keeps the relationship verdict (incl. UNCERTAIN) — they never collapse."""
    case_key: str = ""
    kind: str
    title: str = ""
    source: str = ""
    expected: str = ""
    actual: Optional[str] = None
    outcome: str  # PASS | FAIL | PENDING | NOT_REGISTERED
    confidence: float = 0.0
    reasons: list[Any] = []
    note: str = ""
    relationship_id: Optional[str] = None
    data_mode: str = ""


class EvaluationRunOut(EvaluationResultOut):
    """Result of a (sample-only) live re-run of the reasoner per case."""
    pass


class StatsOut(BaseModel):
    documents: int
    facts: int
    evidence: int
    relationships: dict[str, int]
    provider: str
    embedding_provider: str = ""
    # sample/heuristic | live-llm  — what the corpus was produced by.
    data_mode: str = "sample"
    cases: int = 0
    documents_by_mode: dict[str, int] = {}


FactDetailOut.model_rebuild()
RelationshipDetailOut.model_rebuild()