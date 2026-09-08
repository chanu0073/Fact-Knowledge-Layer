"""Phase 5 — canonical normalisation pass over already-extracted facts.

Deterministic and idempotent: fills/validates ``numeric_value``, ``unit``,
``currency``, ``value_type`` and computes ``period_start``/``period_end``/
``period_type``/``fiscal_year_label`` from ``period_raw``. Does not re-call the
LLM; the extractor's data is treated as source truth and only canonicalised.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, Fact, ProcessingLog
from app.normalize import parse_numeric_value, parse_period, percent_of
from app.processing.parse import detect_unit_and_currency


_MAX = {"entity": 512, "metric": 512, "raw_value": 256, "unit": 64,
        "currency": 16, "period_raw": 128, "observation_type": 24,
        "value_type": 24, "scope": 64, "geography": 64}


def _clamp_lengths(fact: Fact) -> None:
    """Defensive: keep free-form extractor strings inside column widths."""
    for attr, limit in _MAX.items():
        value = getattr(fact, attr)
        if value is not None and len(value) > limit:
            setattr(fact, attr, value[:limit])


def apply_normalization(fact: Fact) -> dict[str, bool]:
    """Canonicalise one fact in place. Returns which fields changed."""
    _clamp_lengths(fact)
    changed = {
        "numeric": False, "unit": False, "value_type": False,
        "period": False, "label": False,
    }

    # numeric_value — only fill when missing (extractor output is canonical).
    if fact.numeric_value is None:
        parsed = parse_numeric_value(fact.raw_value or "")
        if parsed is not None:
            fact.numeric_value = parsed
            changed["numeric"] = True

    # unit / currency — only fill when missing.
    if not (fact.unit or "").strip():
        raw = fact.raw_value or ""
        unit, currency = detect_unit_and_currency(raw)
        if unit:
            fact.unit = unit
            changed["unit"] = True
        if currency and not fact.currency:
            fact.currency = currency

    # value_type — only fill when missing.
    if not (fact.value_type or "").strip():
        raw = fact.raw_value or ""
        fact.value_type = "percent" if percent_of(raw) else "absolute"
        changed["value_type"] = True

    # period — canonical fields are recomputed from period_raw each run.
    info = parse_period(fact.period_raw)
    if info["period_start"] != fact.period_start or info["period_end"] != fact.period_end \
            or info["period_type"] != fact.period_type:
        fact.period_start = info["period_start"]
        fact.period_end = info["period_end"]
        fact.period_type = info["period_type"]
        changed["period"] = True
    label = info["fiscal_year_label"]
    if label != (fact.fiscal_year_label or ""):
        fact.fiscal_year_label = label
        changed["label"] = True

    return changed


async def normalize_facts_for_document(session: AsyncSession, doc: Document) -> dict:
    """Normalise all facts of a document. Idempotent. Returns count summary."""
    res = await session.execute(select(Fact).where(Fact.document_id == doc.id))
    facts = list(res.scalars().all())

    per_field = {"numeric": 0, "unit": 0, "value_type": 0, "period": 0, "label": 0}
    for f in facts:
        ch = apply_normalization(f)
        for k, v in ch.items():
            if v:
                per_field[k] += 1
        session.add(f)

    doc.status = "NORMALIZED"
    session.add(ProcessingLog(
        document_id=doc.id,
        stage="normalize",
        message=f"normalised {len(facts)} facts (periods: {per_field['period']})",
        meta_json={"facts": len(facts), **per_field},
    ))
    return {"facts": len(facts), "changed": per_field}