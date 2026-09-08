"""Provider factory — picks adapters from configuration.

No provider knowledge leaks into the pipeline. ``sample`` (or a missing key
when the provider needs one) falls back to the deterministic offline adapter so
the reviewer can run everything without credentials.
"""
from __future__ import annotations

from app.config import settings
from app.llm.adapters.gemini import GeminiEmbedder, GeminiExtractor, GeminiReasoner
from app.llm.adapters.sample import SampleEmbedder, SampleExtractor, SampleReasoner


def get_extractor():
    """Return the configured fact extractor adapter."""
    provider = settings.llm_provider
    if provider == "gemini":
        if settings.gemini_api_key:
            return GeminiExtractor()
        print("[llm] GEMINI_API_KEY missing — falling back to sample extractor")
    elif provider in ("openai", "anthropic", "openrouter"):
        print(f"[llm] provider '{provider}' not wired yet — falling back to sample extractor")
    return SampleExtractor()


def get_reasoner():
    """Return the configured L2 relationship-judgement adapter."""
    provider = settings.llm_provider
    if provider == "gemini":
        if settings.gemini_api_key:
            return GeminiReasoner()
        print("[llm] GEMINI_API_KEY missing — falling back to sample reasoner")
    elif provider in ("openai", "anthropic", "openrouter"):
        print(f"[llm] provider '{provider}' not wired yet — falling back to sample reasoner")
    return SampleReasoner()


def get_embedder():
    """Return the configured text embedding adapter."""
    provider = settings.embedding_provider
    if provider == "gemini":
        if settings.gemini_api_key:
            return GeminiEmbedder()
        print("[llm] GEMINI_API_KEY missing — falling back to sample embedder")
    elif provider in ("openai", "anthropic", "openrouter"):
        print(f"[llm] provider '{provider}' not wired yet — falling back to sample embedder")
    return SampleEmbedder()