"""Phase 8 — relationship reasoning package.

Layered, deterministic-first:

- ``l1``      — arithmetic verdicts from *normalised* values/periods only.
- ``engine``  — L3 decision fusion: L1 verdict, optionally informed by an L2
               LLM judge for verdicts L1 cannot settle.
"""
from app.reasoning import l1, engine

__all__ = ["l1", "engine"]