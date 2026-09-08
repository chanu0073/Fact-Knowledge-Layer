# Fact Knowledge Layer

A general-purpose **knowledge layer** for financial/enterprise documents: ingest PDFs, extract evidence-grounded,
normalised facts, and discover cross-document relationships (`CORROBORATES`,
`LIKELY_CONTRADICTION`, `APPARENT_CONTRADICTION_RESOLVED`, `UNCERTAIN`).

Built for the **Superjoin VIT 2026 Engineering Intern** assignment. Stack: React + FastAPI + PostgreSQL (pgvector),
LLM provider-agnostic (default Google Gemini, free tier; offline `sample` mode needs no API key).

## Status

- [x] Project scaffolding, Docker stack, REST skeleton with tests
- [x] PostgreSQL + pgvector schema (documents / evidence / facts / relationships / evaluation_cases)
- [x] PDF ingestion → evidence store
- [x] LLM fact extraction + normalisation
- [x] Embeddings + hybrid retrieval
- [x] Relationship reasoning (deterministic + LLM semantics)
- [x] Evaluation harness + 4 demo cases
- [x] Completed API + React UI
- Full roadmap and design history are maintained in a local-only `docs/` folder (kept out of this repository).

## Setup

```bash
# 1) Postgres + pgvector
docker compose up -d db

# 2) Backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example ../.env   # then fill GEMINI_API_KEY (sample mode works without it)
POSTGRES_HOST=localhost .venv/bin/uvicorn app.main:app --reload --port 8000
# API docs → http://localhost:8000/docs

# 3) Frontend
cd ../frontend
npm install && npm run dev   # http://localhost:5173

# 4) Tests (needs the running DB)
cd ../backend
POSTGRES_HOST=localhost .venv/bin/python -m pytest
```

Environment: `LLM_PROVIDER` / `EMBEDDING_PROVIDER` (`gemini | ollama | sample`),
model names, and Postgres credentials — all in `.env` (never committed).

## Demo

- Upload the six sample PDFs (Delhivery prospectus/AR/earnings deck; India Economic Survey / RBI AR / IMF Article IV); the dataset files are kept locally (not part of this repo).
- Dashboard shows document/fact/relationship counts; Explorer lists normalised facts with source page + block;
  Relationships page shows the verdict, confidence, reasons, and side-by-side evidence.
- The four required cases (corroboration, likely contradiction, resolved-by-context, and a deliberate extraction
  failure) are surfaced under **Assignment Cases**.

## Approach

1. **Evidence-first:** every PDF is parsed (pdfplumber + PyMuPDF) into page/block `evidence` rows. A fact exists only
   if it traces to evidence.
2. **Normalised facts:** `raw_value` (exact print) + `numeric_value`/`unit`/`currency` + a temporal model
   (`period_start/end`, `period_type`, `fiscal_year_label`, `observation_type`).
3. **Retrieval ≠ reasoning:** pgvector similarity finds *candidate* fact pairs; the verdict comes from layered
   reasoning — L1 deterministic checks (entity/metric/period/scope/value after normalisation) → L2 LLM semantics
   for ambiguity → L3 final decision. `UNCERTAIN` beats a confident guess.
4. **Provider abstraction:** `GeminiProvider` / `OllamaProvider` (`LLMProvider`) and `GeminiEmbeddingProvider` /
   `LocalEmbeddingProvider` (`EmbeddingProvider`), selected via env and backed by a deterministic `sample` adapter,
   so the full pipeline runs with or without an API key — the core layers have zero provider code.

Detailed design, every decision and its alternatives, and the failure analysis are maintained locally in
`docs/` (ARCHITECTURE.md, DATA_MODEL.md, API.md, DECISIONS.md, EVALUATION.md, FAILURE_ANALYSIS.md,
LEARNING_NOTES.md, INTERVIEW_PREP.md) and are intentionally excluded from this repository.

## Limitations

- Free-tier Gemini rate limits; `sample` mode avoids live-token use in tests.
- Multi-period table extraction (the Case-4 failure mode) is deliberately surfaced as `UNCERTAIN` with reasons rather
  than over-claimed.
- Scanned (image-only) pages cannot be text-extracted reliably.
- Batch processing is in-process/async; no external task queue by design.

## Additional Notes

- `backend/app/` — FastAPI app, async SQLAlchemy, models, config, API routers.
- `frontend/src/` — React (Vite) SPA; plain CSS; routes under `src/pages`.
- `backend/tests/` — API smoke tests against a real PostgreSQL `factknowledge_test` database.
- **Do not commit `.env`** — it holds API keys.