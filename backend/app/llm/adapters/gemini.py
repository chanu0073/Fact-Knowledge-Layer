"""Gemini-backed providers (live API, the target high-fidelity path).

Selected via ``LLM_PROVIDER=gemini`` / ``EMBEDDING_PROVIDER=gemini``.
Uses ``google-genai`` (sync client); calls are CPU/I/O-bound so they run via
``anyio.to_thread``. Free-tier friendly: every call path is paced with a
minimum interval and retries that honour the server's RetryInfo seconds.
No ``response_schema`` is passed: the Gemini API rejects schemas carrying
pydantic defaults, and the structured JSON output is enforced by the prompt +
``response_mime_type`` and parsed back into the pydantic models.
"""
from __future__ import annotations

import time
from pathlib import Path

import anyio
from google import genai

from app.config import settings
from app.llm.base import (
    EMBEDDING_DIM,
    EvidenceBlockSpec,
    ExtractedFact,
    ReasonedConclusion,
)
from app.llm.render import (
    parse_conclusion,
    parse_extraction,
    render_extraction_prompt,
    render_reasoning_prompt,
)

PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "fact_extraction.txt"
REASON_PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "relationship_reasoning.txt"


def _retry_seconds(exc: Exception) -> float:
    """Server-provided 'retry ... s' (RetryInfo) if the error carries one."""
    import re

    m = re.search(r"retry[^\d]{0,20}(\d+(?:\.\d+)?)\s*s", str(exc), re.IGNORECASE)
    return float(m.group(1)) + 2.0 if m else 0.0


class _Pacer:
    """Minimum spacing between live API calls (free-tier friendly)."""

    _last: float = 0.0

    def __init__(self, min_interval: float = 7.0) -> None:
        self.min_interval = min_interval

    def wait(self) -> None:
        elapsed = time.monotonic() - type(self)._last
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        type(self)._last = time.monotonic()


class GeminiProvider:
    """LLMProvider: structured fact extraction + L2 relationship judging."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.model = model or settings.llm_model
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self._prompt = PROMPT_FILE.read_text(encoding="utf-8")
        self._reason_prompt = REASON_PROMPT_FILE.read_text(encoding="utf-8")
        self._pacer = _Pacer()

    def _call_sync(self, prompt: str, prompt_name: str, max_tokens: int):
        from google.genai import types

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1,
            max_output_tokens=max_tokens,
        )
        last_exc: Exception | None = None
        for delay in (5.0, 12.0, 30.0, 60.0, 90.0):
            try:
                self._pacer.wait()
                resp = self.client.models.generate_content(
                    model=self.model, contents=prompt, config=config
                )
                return resp.text
            except Exception as exc:  # rate limit, 5xx, schema hiccup
                last_exc = exc
                time.sleep(max(delay, _retry_seconds(exc)))
        raise RuntimeError(f"Gemini {prompt_name} failed after retries: {last_exc}")

    async def extract(self, blocks: list[EvidenceBlockSpec]) -> list[ExtractedFact]:
        if not blocks:
            return []
        prompt = render_extraction_prompt(self._prompt, blocks)
        text = await anyio.to_thread.run_sync(
            lambda: self._call_sync(prompt, "extraction", 4096)
        )
        return parse_extraction(text)

    async def reason(self, fact_a: dict, fact_b: dict) -> ReasonedConclusion:
        prompt = render_reasoning_prompt(self._reason_prompt, fact_a, fact_b)
        text = await anyio.to_thread.run_sync(
            lambda: self._call_sync(prompt, "reasoning", 1024)
        )
        return parse_conclusion(text)


class GeminiEmbeddingProvider:
    """EmbeddingProvider: gemini-embedding-001 at EMBEDDING_DIM (Matryoshka)."""

    name = "gemini"
    dim = EMBEDDING_DIM
    # Free tier bills *per content item* (~100 contents/minute); keep batches
    # small so retries/backoff suffice.
    batch_size = 20

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.model = model or settings.embedding_model
        self.client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self._pacer = _Pacer(min_interval=3.0)

    def _call_sync(self, texts: list[str]) -> list[list[float]]:
        from google.genai import types

        last_exc: Exception | None = None
        for delay in (1.0, 3.0, 12.0, 30.0, 60.0):
            try:
                self._pacer.wait()
                resp = self.client.models.embed_content(
                    model=self.model,
                    contents=texts,
                    config=types.EmbedContentConfig(output_dimensionality=self.dim),
                )
                return [list(e.values) for e in resp.embeddings]
            except Exception as exc:  # rate limit, 5xx
                last_exc = exc
                time.sleep(max(delay, _retry_seconds(exc)))
        raise RuntimeError(f"Gemini embedding failed after retries: {last_exc}")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            out.extend(await anyio.to_thread.run_sync(self._call_sync, batch))
        return out


# Backwards-compatible aliases (older code/tests referenced the granular names).
GeminiExtractor = GeminiProvider
GeminiReasoner = GeminiProvider
GeminiEmbedder = GeminiEmbeddingProvider