"""Evaluation runner: reason over the demo cases and compare to expectations.

Prints a hit/miss table with the reasons behind each verdict and exits non-zero
on any regression (a case whose actual label differs from its expected label).

Usage:
    cd backend
    LLM_PROVIDER=sample POSTGRES_HOST=localhost .venv/bin/python -m scripts.evaluate
"""
from __future__ import annotations

import asyncio

from app.database import SessionLocal
from app.evaluation.cases import CASES
from app.services.evaluation import run_evaluation


def _row(r: dict) -> str:
    mark = "PASS" if r.get("match") else "FAIL"
    if r.get("actual") == "PENDING" or r.get("actual") == "NO_RELATIONSHIP":
        return f"[{mark}] {r['key']:<24} expected={r['expected']:<24} actual={r['actual']}"
    reasons = "; ".join(r.get("reasons") or [])
    return (
        f"[{mark}] {r['key']:<24} expected={r['expected']:<24} actual={r['actual']}\n"
        f"{'':30} conf={r['confidence']:.2f} reasons={reasons}"
    )


async def main() -> None:
    async with SessionLocal() as session:
        results = await run_evaluation(session, CASES)
    print("== Evaluation ==")
    for r in results:
        print(_row(r))
    passed = sum(1 for r in results if r.get("match"))
    print(f"\n{passed}/{len(results)} cases passed")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())