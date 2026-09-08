"""Shared API response builders (thin mapping layer — no business logic)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Evidence, Fact
from app.schemas import FactOut


async def build_fact_items(session: AsyncSession, facts: list[Fact]) -> list[FactOut]:
    """Enrich facts with the provenance fields the UI traces: owning document
    filename + the earliest source page + grounding kind (block vs page)."""
    if not facts:
        return []

    doc_ids = {f.document_id for f in facts}
    docs = (await session.execute(select(Document).where(Document.id.in_(doc_ids)))).scalars().all()
    filename_by_id = {d.id: d.filename for d in docs}

    all_ev_ids = [eid for f in facts for eid in (f.evidence_ids or [])]
    page_by_id: dict[str, int] = {}
    if all_ev_ids:
        evs = (await session.execute(select(Evidence).where(Evidence.id.in_(all_ev_ids)))).scalars().all()
        for ev in evs:
            page_by_id.setdefault(ev.id, ev.page_number)

    items: list[FactOut] = []
    for f in facts:
        page = min(
            (page_by_id[e] for e in (f.evidence_ids or []) if e in page_by_id),
            default=None,
        )
        grounding = (f.qualifiers or {}).get("grounding", "")
        base = FactOut.model_validate(f)
        items.append(base.model_copy(update={
            "document_filename": filename_by_id.get(f.document_id, ""),
            "page_number": page,
            "grounding": grounding,
        }))
    return items