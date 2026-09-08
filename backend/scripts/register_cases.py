"""Register the four demo cases against the current corpus (dev DB).

Resolves each case's two facts (or builds the synthetic fixture), reasons the
pair, persists the relationship and writes the ``EvaluationCase`` row. Idempotent.

Usage:
    cd backend
    LLM_PROVIDER=sample POSTGRES_HOST=localhost .venv/bin/python -m scripts.register_cases
"""
from __future__ import annotations

import asyncio

from app.database import SessionLocal
from app.evaluation.cases import CASES
from app.services.evaluation import register_cases


async def main() -> None:
    async with SessionLocal() as session:
        results = await register_cases(session, CASES)
        await session.commit()
    for r in results:
        status = r["status"]
        note = r.get("note", "")
        extra = ""
        if r["status"] == "registered":
            extra = f" -> {r['actual']} {'✔' if r['match'] else '✘ expected ' + r['expected']}"
        print(f"[{status:>10}] {r['key']:<24} {extra} {note}")


if __name__ == "__main__":
    asyncio.run(main())