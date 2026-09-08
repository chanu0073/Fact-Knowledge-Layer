"""Application configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root if present (never committed).
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(ROOT_DIR / ".env")


class Settings:
    """Simple settings holder. Values read from env with safe defaults."""

    # App
    app_name: str = os.getenv("APP_NAME", "Fact Knowledge Layer")
    app_env: str = os.getenv("APP_ENV", "development")
    debug: bool = os.getenv("DEBUG", "true").lower() in ("1", "true", "yes")

    # LLM / embeddings provider abstraction
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini").lower()
    embedding_provider: str = os.getenv("EMBEDDING_PROVIDER", "gemini").lower()
    llm_model: str = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
    # gemini-embedding-001 supports reduced dims (Matryoshka). Must be <= 2000 so
    # an HNSW/IVFFlat pgvector index is allowed.
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "1536"))

    # Provider keys
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")

    # PostgreSQL
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "factknowledge")
    postgres_user: str = os.getenv("POSTGRES_USER", "factuser")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "factpass")

    # Uploads
    upload_dir: Path = ROOT_DIR / "data" / "uploads"
    max_upload_mb: int = int(os.getenv("MAX_UPLOAD_MB", "100"))

    # Period normalisation
    fiscal_year_start_month: int = int(os.getenv("FISCAL_START_MONTH", "4"))

    # Relationship reasoning (Phase 8)
    reasoning_candidate_limit: int = int(os.getenv("REASONING_CANDIDATE_LIMIT", "10"))
    max_l2_calls: int = int(os.getenv("MAX_L2_CALLS", "50"))

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def sync_database_url(self) -> str:
        """Used by any sync context (e.g. lightweight scripts)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")

    @property
    def llm_enabled(self) -> bool:
        """True when a real provider key is configured (not sample mode)."""
        keys = {
            "gemini": self.gemini_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
            "openrouter": self.openrouter_api_key,
        }
        return bool(keys.get(self.llm_provider, ""))


settings = Settings()