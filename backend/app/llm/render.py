"""Provider-shared prompt rendering and lenient JSON parsing.

Kept outside the provider adapters so no provider-specific logic leaks into
the extraction/normalisation/reasoning core; both Gemini and Ollama (and any
future provider) render the same evidence→prompt shape and parse the same
structured response.
"""
from __future__ import annotations

import json

from app.llm.base import EvidenceBlockSpec, ExtractedFact, ReasonedConclusion


def render_extraction_prompt(base_prompt: str, blocks: list[EvidenceBlockSpec]) -> str:
    lines = [
        f"[{b.index}] page {b.page_number} ({b.evidence_type})\n{b.content}"
        for b in blocks
    ]
    return base_prompt + "\n\n=== EVIDENCE ===\n" + "\n\n".join(lines)


def _block(label: str, fact: dict) -> str:
    lines = [
        f"{label}:",
        f"  entity: {fact.get('entity')}",
        f"  metric: {fact.get('metric')}",
        f"  definition: {fact.get('definition') or '-'}",
        f"  value: {fact.get('numeric_value')} {fact.get('unit')} {fact.get('currency')} ({fact.get('raw_value')})",
        f"  value_type: {fact.get('value_type')}",
        f"  period: {fact.get('period_raw')} | label: {fact.get('fiscal_year_label')}",
        f"  observation: {fact.get('observation_type')}",
        f"  scope: {fact.get('scope')} | geography: {fact.get('geography')}",
        "  evidence: " + " ".join(fact.get("evidence") or []) or "-",
    ]
    return "\n".join(lines)


def render_reasoning_prompt(base_prompt: str, fact_a: dict, fact_b: dict) -> str:
    return base_prompt + "\n\n=== PAIR ===\n" + _block("FACT A", fact_a) + "\n\n" + _block("FACT B", fact_b)


def parse_extraction(text: str) -> list[ExtractedFact]:
    """Lenient parse of an LLM JSON reply into structured facts."""
    text = (text or "{}").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            payload = json.loads(text[start : end + 1])
        else:
            raise
    facts = [_coerce_qualifiers(f) for f in payload.get("facts", [])]
    return [ExtractedFact.model_validate(f) for f in facts]


def _coerce_qualifiers(fact: dict) -> dict:
    """Ollama small models sometimes emit ``qualifiers: []`` — normalise to {}."""
    q = fact.get("qualifiers")
    if isinstance(q, list):
        fact = dict(fact)
        fact["qualifiers"] = {}
    return fact


def parse_conclusion(text: str) -> ReasonedConclusion:
    """Lenient parse of an L2 judge JSON reply."""
    text = (text or "{}").strip()
    try:
        return ReasonedConclusion(**json.loads(text))
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return ReasonedConclusion(**json.loads(text[start : end + 1]))
        raise