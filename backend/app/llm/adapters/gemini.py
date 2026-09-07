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
from app.llm.base import EvidenceBlockSpec, ExtractedFact

PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "fact_extraction.txt"


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