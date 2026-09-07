"""Fact extraction orchestration: evidence blocks → validated Fact rows.

Guarantees (the assignment's evidence-grounding rules):
- a Fact is never created without at least one linked evidence id;
- if the extractor leaves ``source_block_indices`` empty we bind the fact to
  the page's blocks but mark ``qualifiers["grounding"] = "page"`` and penalise
  confidence — strictly worse than block-level grounding, never discarded silently;
- the extractor's exact output is preserved in ``raw_extraction_json`` for audit.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.base import EvidenceBlockSpec, ExtractedFact
from app.llm.factory import get_extractor
from app.models import Document, Evidence, Fact, ProcessingLog


def block_specs(evidence_rows: list[Evidence]) -> list[EvidenceBlockSpec]:
    return [
        EvidenceBlockSpec(index=i, page_number=e.page_number, evidence_type=e.evidence_type, content=e.content)
        for i, e in enumerate(evidence_rows)
    ]


def evidence_by_id(evidence_rows: list[Evidence]) -> dict[str, Evidence]:
    return {e.id: e for e in evidence_rows}


def build_fact(
    document_id: str,
    ef: ExtractedFact,
    rows: list[Evidence],
    specs: list[EvidenceBlockSpec],
) -> Fact | None:
    """Map an ExtractedFact to a Fact row, enforcing the evidence-grounding rule."""
    # Minimal viability: something to say.
    has_value = bool(ef.raw_value.strip()) or ef.numeric_value is not None
    if not has_value or not ef.metric.strip():
        return None

    spec_by_index = {s.index: s for s in specs}
    id_by_index = {s.index: r.id for s, r in zip(specs, rows)}

    idxs = [id_by_index[i] for i in ef.source_block_indices if i in id_by_index]
    grounding = "block"
    if not idxs:
        idxs = [r.id for r in rows]
        grounding = "page"

    confidence = max(0.0, min(1.0, ef.confidence))
    if grounding == "page":
        confidence *= 0.8

    qualifiers = dict(ef.qualifiers or {})
    qualifiers["grounding"] = grounding

    return Fact(
        document_id=document_id,
        evidence_ids=idxs,
        entity=(ef.entity or "unknown").strip(),
        metric=ef.metric.strip(),
        definition=ef.definition,
        raw_value=ef.raw_value,
        numeric_value=ef.numeric_value,
        unit=ef.unit,
        currency=ef.currency,
        value_type=ef.value_type,
        period_raw=ef.period_raw,
        period_start=None,  # computed in Phase 5 (normalisation)
        period_end=None,
        period_type=ef.period_type,
        fiscal_year_label=ef.fiscal_year_label,
        observation_type=ef.observation_type,
        scope=ef.scope,
        geography=ef.geography,
        qualifiers=qualifiers,
        extraction_confidence=confidence,
        raw_extraction_json=ef.model_dump(),
    )


async def extract_facts_for_document(
    session: AsyncSession,
    doc: Document,
    extractor=None,
) -> dict[str, int]:
    """Run extraction for a parsed document (per page). Returns {"created": n, "skipped": n}."""
    extractor = extractor or get_extractor()
    if doc.status == "UPLOADED":
        raise RuntimeError(f"Document {doc.filename} must be parsed before extraction")

    res = await session.execute(
        select(Evidence).where(Evidence.document_id == doc.id).order_by(Evidence.page_number, Evidence.block_index)
    )
    rows = list(res.scalars().all())
    if not rows:
        raise RuntimeError(f"Document {doc.filename} has no evidence to extract from")

    # Idempotent: replacement run.
    await session.execute(delete(Fact).where(Fact.document_id == doc.id))
    await session.flush()

    pages: dict[int, list[Evidence]] = defaultdict(list)
    for r in rows:
        pages[r.page_number].append(r)

    created = 0
    skipped = []
    for page_no in sorted(pages):
        page_rows = pages[page_no]
        specs = block_specs(page_rows)
        try:
            efacts = await extractor.extract(specs)
        except Exception as exc:
            skipped.append(f"p{page_no}: {exc}")
            continue

        for ef in efacts:
            fact = build_fact(doc.id, ef, page_rows, specs)
            if fact is None:
                skipped.append(f"p{page_no}: unviable {ef.metric!r}")
                continue
            session.add(fact)
            created += 1

    doc.status = "EXTRACTED"
    session.add(ProcessingLog(
        document_id=doc.id,
        stage="extract",
        message=f"extracted {created} facts from {len(rows)} evidence blocks",
        meta_json={"created": created, "page_issues": skipped[:20]},
    ))
    return {"created": created, "skipped": len(skipped)}