"""Provider factory — picks LLM/embedding adapters from configuration.

The pipeline never talks to a provider SDK directly; it only handles the
``FactExtractor`` / ``RelationshipReasoner`` / ``Embedder`` shapes returned
here. ``LLM_PROVIDER`` / ``EMBEDDING_PROVIDER`` select the backing:

  LLM_PROVIDER ∈ gemini | ollama | sample
  EMBEDDING_PROVIDER ∈ gemini | ollama | sample

- ``gemini`` — target high-fidelity provider (accurate financial extraction).
- ``ollama`` — local, offline-capable provider (dev/fallback while Gemini
  quota is unavailable or to avoid cloud calls).
- ``sample`` — deterministic offline provider, always works, used by tests.

Missing credentials for a cloud provider log a warning and fall back to the
offline ``sample`` provider so the reviewer can run everything unauthenticated.
"""
from __future__ import annotations

from app.config import settings
from app.llm.adapters.gemini import GeminiEmbeddingProvider, GeminiProvider
from app.llm.adapters.ollama import LocalEmbeddingProvider, OllamaProvider
from app.llm.adapters.sample import SampleEmbedder, SampleExtractor, SampleReasoner


def get_extractor():
    """Return the configured fact extractor (has ``.extract``)."""
    provider = settings.llm_provider
    if provider == "gemini":
        if settings.gemini_api_key:
            return GeminiProvider()
        print("[llm] GEMINI_API_KEY missing — falling back to sample extractor")
    elif provider == "ollama":
        return OllamaProvider()
    elif provider == "sample":
        return SampleExtractor()
    else:
        print(f"[llm] unknown LLM_PROVIDER '{provider}' — falling back to sample extractor")
    return SampleExtractor()


def get_reasoner():
    """Return the configured L2 relationship judge (has ``.reason``)."""
    provider = settings.llm_provider
    if provider == "gemini":
        if settings.gemini_api_key:
            return GeminiProvider()
        print("[llm] GEMINI_API_KEY missing — falling back to sample reasoner")
    elif provider == "ollama":
        return OllamaProvider()
    elif provider == "sample":
        return SampleReasoner()
    else:
        print(f"[llm] unknown LLM_PROVIDER '{provider}' — falling back to sample reasoner")
    return SampleReasoner()


def get_embedder():
    """Return the configured text embedding adapter (has ``.embed``)."""
    provider = settings.embedding_provider
    if provider == "gemini":
        if settings.gemini_api_key:
            return GeminiEmbeddingProvider()
        print("[llm] GEMINI_API_KEY missing — falling back to sample embedder")
    elif provider in ("ollama", "local"):
        return LocalEmbeddingProvider()
    elif provider == "sample":
        return SampleEmbedder()
    else:
        print(f"[llm] unknown EMBEDDING_PROVIDER '{provider}' — falling back to sample embedder")
    return SampleEmbedder()