"""Phase 9 — evaluation harness services.

Two jobs:

- ``register_cases`` — materialise each demo case against a corpus: resolve (or
  build, for synthetic fixtures) the two facts, run the real reasoner over the
  pair, persist the relationship, and write an ``EvaluationCase`` row with the
  expected label, fact ids and relationship link.
- ``run_evaluation`` — for every case, run the reasoner and compare to the
  expected label (the comparison table / regression gate).

Both are idempotent and reason about pairs directly (``decide_pair``), so
within-document pairs (e.g. synthetic fixtures, prospectus tables) are handled
even though the retrieval pipeline only produces cross-document candidates.
"""
from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.evaluation.cases import CASES, CaseDef
from app.llm.factory import get_reasoner
from app.models import Document, EvaluationCase, Fact, Relationship
from app.reasoning.engine import decide_pair

_FILTER_COLUMNS = ("entity", "metric", "period_type", "fiscal_year_label")


async def resolve_fact(session: AsyncSession, filters: dict) -> Fact | None:
    """Locate one fact by filters: direct Fact-column equality, a ``doc``
    substring of the owning document's filename, and ``period_raw_contains``."""
    stmt = select(Fact).join(Document, Document.id == Fact.document_id)
    for col in _FILTER_COLUMNS:
        if filters.get(col):
            stmt = stmt.where(getattr(Fact, col) == filters[col])
    if filters.get("period_raw_contains"):
        stmt = stmt.where(Fact.period_raw.ilike(f"%{filters['period_raw_contains']}%"))
    if filters.get("doc"):
        stmt = stmt.where(Document.filename.ilike(f"%{filters['doc']}%"))
    stmt = stmt.order_by(Fact.created_at.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def _resolve_or_build(session: AsyncSession, case: CaseDef) -> tuple[Fact | None, Fact | None]:
    if not case.synthetic_facts:
        return (
            await resolve_fact(session, case.fact_a),
            await resolve_fact(session, case.fact_b),
        )
    # (Re)create the synthetic fixture documents + facts (idempotent).
    doc = (
        await session.execute(select(Document).where(Document.filename == case.synthetic_doc))
    ).scalar_one_or_none()
    if doc is None:
        doc = Document(filename=case.synthetic_doc, stored_path="", sha256="",
                       status="EMBEDDED", page_count=1,
                       data_mode="fixture", provider="fixture")
        session.add(doc)
        await session.flush()
    res = await session.execute(select(Fact).where(Fact.document_id == doc.id))
    for f in res.scalars().all():
        await session.delete(f)
    await session.flush()

    facts: list[Fact] = []
    for kw in case.synthetic_facts:
        kw = dict(kw)
        qualifiers = dict(kw.pop("qualifiers", {}))
        kw.setdefault("evidence_ids", [])
        facts.append(Fact(document_id=doc.id, qualifiers=qualifiers, **kw))
    session.add_all(facts)
    await session.flush()
    return facts[0], facts[1]


async def _store_relationship(session: AsyncSession, fa: Fact, fb: Fact, decision) -> Relationship:
    """Upsert the relationship for the pair (either ordering)."""
    res = await session.execute(
        select(Relationship).where(
            or_(
                and_(Relationship.fact_a_id == fa.id, Relationship.fact_b_id == fb.id),
                and_(Relationship.fact_a_id == fb.id, Relationship.fact_b_id == fa.id),
            )
        )
    )
    rel = res.scalar_one_or_none()
    a_id, b_id = sorted((fa.id, fb.id))
    if rel is None:
        rel = Relationship(fact_a_id=a_id, fact_b_id=b_id)
        session.add(rel)
    rel.relationship_type = decision.label
    rel.confidence = decision.confidence
    rel.reasons = decision.reasons
    rel.llm_reasoning = decision.llm_reasoning
    rel.evidence_json = {
        "periods_overlap": decision.periods_overlap,
        "l1_label": decision.l1_label,
        "l1_strength": decision.l1_strength,
        "case": "evaluation",
    }
    rel.is_synthetic = decision.is_synthetic
    await session.flush()
    return rel


async def register_cases(session: AsyncSession, defs: list[CaseDef] | None = None, reasoner=None) -> list[dict]:
    """Register every demo case against the corpus. Returns per-case status."""
    reasoner = reasoner or get_reasoner()
    results: list[dict] = []

    for case in defs or CASES:
        fa, fb = await _resolve_or_build(session, case)
        if fa is None or fb is None or fa.id == fb.id:
            results.append({"key": case.key, "kind": case.kind, "status": "pending",
                            "expected": case.expected_relationship, "note": "facts not found in corpus"})
            continue

        decision = await decide_pair(session, fa, fb, reasoner)
        if decision is None:
            results.append({"key": case.key, "kind": case.kind, "status": "pending",
                            "expected": case.expected_relationship, "note": "pair not comparable"})
            continue

        rel = await _store_relationship(session, fa, fb, decision)

        old = (await session.execute(
            select(EvaluationCase).where(EvaluationCase.kind == case.kind)
        )).scalar_one_or_none()
        if old is not None:
            await session.delete(old)
        session.add(EvaluationCase(
            kind=case.kind,
            source=case.source,
            title=case.title,
            description=case.description,
            explanation=case.explanation,
            relationship_id=rel.id,
            fact_ids=[fa.id, fb.id],
            expected_relationship=case.expected_relationship,
        ))
        results.append({"key": case.key, "kind": case.kind, "status": "registered",
                        "expected": case.expected_relationship,
                        "actual": decision.label,
                        "match": decision.label == case.expected_relationship,
                        "confidence": decision.confidence,
                        "reasons": decision.reasons,
                        "note": f"{fa.entity} {fa.metric} ({fa.raw_value}) vs "
                                f"{fb.entity} {fb.metric} ({fb.raw_value})"})
    return results


async def run_evaluation(session: AsyncSession, defs: list[CaseDef] | None = None, reasoner=None) -> list[dict]:
    """Re-run the reasoner over each case and compare to the expected label.
    Read-only w.r.t. relationships (persists nothing)."""
    reasoner = reasoner or get_reasoner()
    out: list[dict] = []
    for case in defs or CASES:
        fa, fb = await _resolve_or_build(session, case)
        if fa is None or fb is None or fa.id == fb.id:
            out.append({"key": case.key, "expected": case.expected_relationship,
                        "actual": "PENDING", "match": False,
                        "reason": "facts not found in corpus"})
            continue
        decision = await decide_pair(session, fa, fb, reasoner)
        actual = decision.label if decision else "NO_RELATIONSHIP"
        out.append({
            "key": case.key,
            "expected": case.expected_relationship,
            "actual": actual,
            "match": actual == case.expected_relationship,
            "confidence": decision.confidence if decision else 0.0,
            "reasons": decision.reasons if decision else [],
        })
    return out


async def case_statuses(session: AsyncSession, defs: list[CaseDef] | None = None) -> list[dict]:
    """Static per-case outcome from persisted rows — no LLM, no writes.

    outcome semantics (deliberately distinct from relationship labels):
    - PASS             registered relationship matches the expected label
    - FAIL             registered relationship exists but differs
    - PENDING          case row present but no relationship yet (facts unresolved)
    - NOT_REGISTERED   case not registered against this corpus
    """
    statuses: dict[str, dict] = {}
    for case in defs or CASES:
        statuses[case.key] = {
            "case_key": case.key,
            "kind": case.kind,
            "title": case.title,
            "source": case.source,
            "expected": case.expected_relationship,
            "outcome": "NOT_REGISTERED",
        }

    rows = (await session.execute(select(EvaluationCase))).scalars().all()
    rel_ids = [c.relationship_id for c in rows if c.relationship_id]
    rels: dict[str, Relationship] = {}
    if rel_ids:
        res = await session.execute(select(Relationship).where(Relationship.id.in_(rel_ids)))
        rels = {r.id: r for r in res.scalars().all()}

    for row in rows:
        key = _case_key_for_row(row)
        known = key in statuses
        if known:
            base = statuses[key]
        else:
            # Row from a case definition we don't know — surface it as-is.
            base = {
                "case_key": key,
                "kind": row.kind,
                "title": row.title,
                "source": row.source,
                "expected": row.expected_relationship,
                "outcome": "NOT_REGISTERED",
            }
            statuses[key] = base
        rel = rels.get(row.relationship_id or "")
        base.update({
            "source": row.source,
            "expected": row.expected_relationship,
            "relationship_id": row.relationship_id,
        })
        if known:
            base["title"] = row.title or base.get("title", "")
        if rel is None:
            base["outcome"] = "PENDING"
            base["note"] = "case registered but no relationship resolved"
            continue
        base["outcome"] = "PASS" if rel.relationship_type == row.expected_relationship else "FAIL"
        base["actual"] = rel.relationship_type
        base["confidence"] = rel.confidence
        base["reasons"] = rel.reasons or []
        base["note"] = "registered relationship matches expected label" if base["outcome"] == "PASS" else "registered relationship differs from expected label"

    return list(statuses.values())


def _case_key_for_row(row: EvaluationCase) -> str:
    """Map an EvaluationCase row back to its CaseDef key where possible."""
    for case in CASES:
        if case.kind == row.kind and case.expected_relationship == row.expected_relationship:
            return case.key
    return row.kind