"""Gemini-backed extractor (live API).

Uses ``google-genai`` (sync client) with a JSON response schema. The call is
CPU/I/O-bound so callers drive it via ``anyio.to_thread``. Free-tier friendly:
small retry/backoff on rate limits, and clients are expected to batch by page.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import anyio
from pydantic import BaseModel, Field

from app.config import settings
from app.llm.base import EMBEDDING_DIM, EvidenceBlockSpec, ExtractedFact, ReasonedConclusion

PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "fact_extraction.txt"
REASON_PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "relationship_reasoning.txt"


class ExtractionResponse(BaseModel):
    facts: list[ExtractedFact] = Field(default_factory=list)


class GeminiExtractor:
    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from google import genai

        self.model = model or settings.llm_model
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self._prompt = PROMPT_FILE.read_text(encoding="utf-8")

    def _render(self, blocks: list[EvidenceBlockSpec]) -> tuple[str, list[str]]:
        """Return (prompt, ordering of evidence ids via block.index)."""
        lines = [
            f"[{b.index}] page {b.page_number} ({b.evidence_type})\n{b.content}"
            for b in blocks
        ]
        return self._prompt + "\n\n=== EVIDENCE ===\n" + "\n\n".join(lines), []

    def _call_sync(self, prompt: str) -> ExtractionResponse:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractionResponse,
            temperature=0.1,
            max_output_tokens=4096,
        )
        last_exc: Exception | None = None
        for attempt in range(1, 5):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                text = (resp.text or "{}").strip()
                # Some models ignore response_schema; fall back to lenient parsing.
                try:
                    return ExtractionResponse(**json.loads(text))
                except json.JSONDecodeError:
                    start = text.find("{")
                    end = text.rfind("}")
                    if start != -1 and end > start:
                        return ExtractionResponse(**json.loads(text[start : end + 1]))
                    raise
            except Exception as exc:  # rate limit, 5xx, schema hiccup
                last_exc = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Gemini extraction failed after retries: {last_exc}")

    async def extract(self, blocks: list[EvidenceBlockSpec]) -> list[ExtractedFact]:
        if not blocks:
            return []
        prompt, _ = self._render(blocks)
        return (await anyio.to_thread.run_sync(self._call_sync, prompt)).facts


class GeminiEmbedder:
    name = "gemini"
    dim = EMBEDDING_DIM
    # Free tier bills *per content item* (~100 contents/minute); a batch of 100
    # in one call burns the whole minute. Keep small so retries/backoff suffice.
    batch_size = 20

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from google import genai

        self.model = model or settings.embedding_model
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)

    @staticmethod
    def _retry_delay(exc: Exception) -> float:
        import re

        m = re.search(r"retry[^\d]{0,20}(\d+(?:\.\d+)?)\s*s", str(exc), re.IGNORECASE)
        return float(m.group(1)) + 2.0 if m else 0.0

    def _call_sync(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        last_exc: Exception | None = None
        # exponential backoff with explicit respect for the server's RetryInfo
        for attempt, delay in enumerate((1.0, 3.0, 12.0, 30.0)):
            try:
                resp = self.client.models.embed_content(
                    model=self.model,
                    contents=texts,
                    config=types.EmbedContentConfig(output_dimensionality=self.dim),
                )
                return [list(e.values) for e in resp.embeddings]
            except Exception as exc:  # rate limit, 5xx
                last_exc = exc
                time.sleep(max(delay, self._retry_delay(exc)))
        raise RuntimeError(f"Gemini embedding failed after retries: {last_exc}")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            out.extend(await anyio.to_thread.run_sync(self._call_sync, batch))
        return out


class GeminiReasoner:
    """Live LLM judge for L2 — two facts + evidence → one of the 4 labels."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        from google import genai

        self.model = model or settings.llm_model
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self._prompt = REASON_PROMPT_FILE.read_text(encoding="utf-8")

    def _render(self, fact_a: dict, fact_b: dict) -> str:
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

        return self._prompt + "\n\n=== PAIR ===\n" + _block("FACT A", fact_a) + "\n\n" + _block("FACT B", fact_b)

    def _call_sync(self, prompt: str) -> ReasonedConclusion:
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ReasonedConclusion,
            temperature=0.1,
            max_output_tokens=1024,
        )
        last_exc: Exception | None = None
        for attempt in range(1, 5):
            try:
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                text = (resp.text or "{}").strip()
                try:
                    return ReasonedConclusion(**json.loads(text))
                except json.JSONDecodeError:
                    start = text.find("{")
                    end = text.rfind("}")
                    if start != -1 and end > start:
                        return ReasonedConclusion(**json.loads(text[start : end + 1]))
                    raise
            except Exception as exc:  # rate limit, 5xx, schema hiccup
                last_exc = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Gemini reasoning failed after retries: {last_exc}")

    async def reason(self, fact_a: dict, fact_b: dict) -> ReasonedConclusion:
        return await anyio.to_thread.run_sync(self._call_sync, self._render(fact_a, fact_b))