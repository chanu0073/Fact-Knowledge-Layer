"""Ollama-backed LLM + local embedding providers (offline-capable).

Selected via ``LLM_PROVIDER=ollama`` / ``EMBEDDING_PROVIDER=ollama``. Talks to a
local ``ollama serve`` over ``/api/generate`` (JSON mode) and ``/api/embed``.
No cloud calls: the local-dev / fallback story while Gemini is quota-gated or
offline. Embedding vectors are zero-padded to ``EMBEDDING_DIM`` when the local
model emits fewer dimensions so the fixed-width ``pgvector`` column stays
uniform across providers.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.config import settings
from app.llm.base import EMBEDDING_DIM, EvidenceBlockSpec, ExtractedFact, ReasonedConclusion
from app.llm.render import parse_conclusion, parse_extraction, render_extraction_prompt, render_reasoning_prompt

EXTRACT_PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "fact_extraction.txt"
REASON_PROMPT_FILE = Path(__file__).resolve().parents[3] / "prompts" / "relationship_reasoning.txt"

# Small enough to leave headroom for the KV cache on a 4 GB laptop GPU.
_NUM_CTX = 8192
_BATCH = 8


class OllamaProvider:
    """LLMProvider: structured fact extraction + L2 relationship judging."""

    name = "ollama"

    def __init__(self, url: str | None = None, model: str | None = None) -> None:
        self.url = url or settings.ollama_url
        self.model = model or settings.ollama_model
        self._extract_prompt = EXTRACT_PROMPT_FILE.read_text(encoding="utf-8")
        self._reason_prompt = REASON_PROMPT_FILE.read_text(encoding="utf-8")

    async def _generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_ctx": _NUM_CTX},
        }
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=300) as client:
            for attempt in range(4):
                try:
                    resp = await client.post(f"{self.url}/api/generate", json=payload)
                    resp.raise_for_status()
                    body = resp.json()
                    if body.get("error"):
                        raise RuntimeError(body["error"])
                    return body.get("response", "") or "{}"
                except Exception as exc:  # server warming up, transient 5xx, model error
                    last = exc
                    await asyncio.sleep(1.5 * (2 ** attempt))
        raise RuntimeError(
            f"Ollama generation failed after retries ({self.url}, {self.model}): {last}"
        )

    async def extract(self, blocks: list[EvidenceBlockSpec]) -> list[ExtractedFact]:
        if not blocks:
            return []
        return parse_extraction(await self._generate(render_extraction_prompt(self._extract_prompt, blocks)))

    async def reason(self, fact_a: dict, fact_b: dict) -> ReasonedConclusion:
        return parse_conclusion(await self._generate(render_reasoning_prompt(self._reason_prompt, fact_a, fact_b)))


class LocalEmbeddingProvider:
    """EmbeddingProvider: local embeddings via Ollama, padded to EMBEDDING_DIM."""

    name = "ollama"
    dim = EMBEDDING_DIM

    def __init__(self, url: str | None = None, model: str | None = None) -> None:
        self.url = url or settings.ollama_url
        self.model = model or settings.ollama_embedding_model

    @classmethod
    def _pad(cls, vector: list[float]) -> list[float]:
        n = len(vector)
        if n == cls.dim:
            return vector
        if n > cls.dim:
            return vector[: cls.dim]
        return vector + [0.0] * (cls.dim - n)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=300) as client:
            for start in range(0, len(texts), _BATCH):
                batch = texts[start : start + _BATCH]
                for attempt in range(4):
                    try:
                        resp = await client.post(
                            f"{self.url}/api/embed",
                            json={"model": self.model, "input": batch},
                        )
                        resp.raise_for_status()
                        vecs = resp.json().get("embeddings", [])
                        if len(vecs) != len(batch):
                            raise RuntimeError(f"Ollama embed returned {len(vecs)} vectors for {len(batch)} texts")
                        out.extend(self._pad(list(v)) for v in vecs)
                        break
                    except Exception as exc:
                        last = exc
                        await asyncio.sleep(1.5 * (2 ** attempt))
                else:
                    raise RuntimeError(
                        f"Ollama embedding failed after retries ({self.url}, {self.model}): {last}"
                    )
        return out