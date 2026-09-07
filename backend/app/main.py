"""FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.database import engine, SessionLocal
from app.db.init import init_db
from app.schemas import HealthOut
from app.api import documents, facts, relationships, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
    except Exception as exc:  # DB may be starting; surfaced by /health
        print(f"[warn] schema init skipped: {exc}")
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local dev; tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(documents.router)
app.include_router(facts.router)
app.include_router(relationships.router)


@app.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    db_ok = False
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False
    return HealthOut(
        status="ok" if db_ok else "degraded",
        app=settings.app_name,
        version="0.1.0",
        db_ok=db_ok,
        provider=settings.llm_provider,
    )


@app.get("/")
async def root() -> dict:
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/health"}