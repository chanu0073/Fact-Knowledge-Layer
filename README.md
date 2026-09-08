# Fact Knowledge Layer

A general-purpose **knowledge layer** for financial/enterprise documents: ingest PDFs, extract evidence-grounded,
normalised facts, and discover cross-document relationships (`CORROBORATES`,
`LIKELY_CONTRADICTION`, `APPARENT_CONTRADICTION_RESOLVED`, `UNCERTAIN`).

Built for the **Superjoin VIT 2026 Engineering Intern** assignment. Stack: React + FastAPI + PostgreSQL (pgvector),
LLM provider-agnostic (default Google Gemini, free tier; offline `sample` mode needs no API key).

## Setup and Run Instructions

Prerequisites: Docker (Postgres+pgvector), Python 3.10+, Node 18+.

```bash
# 1) Postgres + pgvector
docker compose up -d db

# 2) Backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp ../.env.example .env        # fill GEMINI_API_KEY only if you want live mode; sample works without it
POSTGRES_HOST=localhost .venv/bin/uvicorn app.main:app --reload --port 8000
# API docs → http://localhost:8000/docs

# 3) Frontend
cd ../frontend
npm install && npm run dev     # http://localhost:5173

# 4) Tests (needs the running DB)
cd ../backend
POSTGRES_HOST=localhost .venv/bin/python -m pytest    # 94 passed
```

**Accepting new PDFs** — via the UI (Documents → upload) or the API:
`POST /api/documents/upload` (multipart `files`). Each upload lands as an `UPLOADED` row; process it with
`POST /api/documents/{id}/pipeline` (202 + `QUEUED`, then poll status until `REASONED`/`FAILED`) or the **Re-run
full pipeline** button on the document page. Reproduce the demo corpus + the four evaluation cases offline:

```bash
cd backend && LLM_PROVIDER=sample EMBEDDING_PROVIDER=sample POSTGRES_HOST=localhost \
  .venv/bin/python -m scripts.run_pipeline "<pdf1>" "<pdf2>" ...   # ingest the six starter PDFs
LLM_PROVIDER=sample POSTGRES_HOST=localhost .venv/bin/python -m scripts.register_cases
LLM_PROVIDER=sample POSTGRES_HOST=localhost .venv/bin/python -m scripts.evaluate
```

Environment (`LLM_PROVIDER` / `EMBEDDING_PROVIDER` ∈ `gemini | ollama | sample`), model names, and Postgres
credentials all live in `.env` (never committed — only `.env.example` is checked in, with placeholders).

## Video Demo

Demo video (≤ 3 min): **`[PASTE YOUR YOUTUBE/DRIVE LINK HERE]`**

It shows: uploading a PDF through the UI → the pipeline progressing stage-by-stage
(`PARSING → … → REASONING`) → the dashboard with document/fact/relationship counts → a document trace down to
evidence blocks → relationship verdicts with reasons → the four assignment cases on the **Assignment Cases**
page (case 2 resolves live on the sample corpus; the deterministic harness and test suite prove cases 1, 3 and 4
offline, see *Additional Notes*).

## Approach

1. **Evidence-first:** every PDF is parsed (pdfplumber + PyMuPDF) into page/block `evidence` rows. A fact exists only
   if it traces to evidence.
2. **Normalised facts:** `raw_value` (exact print) + `numeric_value`/`unit`/`currency` + a temporal model
   (`period_start/end`, `period_type`, `fiscal_year_label`, `observation_type`), so comparable facts from different
   documents converge on one representation.
3. **Retrieval ≠ reasoning:** pgvector (HNSW) similarity finds *candidate* fact pairs; the verdict comes from layered
   reasoning — L1 deterministic checks (entity/metric/period/scope/value after normalisation) → L2 LLM semantics for
   ambiguity → L3 final decision. `UNCERTAIN` beats a confident guess.
4. **Provider abstraction:** `GeminiProvider` / `OllamaProvider` (`LLMProvider`) and `GeminiEmbeddingProvider` /
   `LocalEmbeddingProvider` (`EmbeddingProvider`), selected via env and backed by a deterministic `sample` adapter,
   so the full pipeline runs with or without an API key — the core layers have zero provider code.
5. **API + UI over the same model:** a uniform REST API (single error envelope, per-document provenance endpoints,
   background pipeline with status polling) and a React SPA that is a lossless projection of it.

**Important decisions and trade-offs**

- *Honesty over hallucination:* every refusal path (`UNCERTAIN`, multi-period table Case 4, differing currencies)
  is stated openly with reasons, never silently guessed.
- *Deterministic sample mode* was rebuilt (not stubbed) so the entire pipeline, all tests, and 1 of 4 live demo cases
  run with **no API key**; live Gemini is an env switch away.
- *Background task instead of an external queue:* in-process async + 2-second polling is deliberately simple for this
  scale; the task owns its own injectable session so tests exercise the real pipeline.
- *Public errors are sanitized:* 500s and stored `error_message` carry a fixed generic message; raw detail is
  server-log only — nothing internal (paths/tracebacks) leaks through the API.
- *Synthetic fixtures for evaluation:* a clearly-labelled fixture proves the contradiction verdict offline; the other
  three verdict shapes are pinned by deterministic tests against a controlled corpus.

**AI tools used** — an AI pair-programming assistant (opencode) was used for scaffolding, implementation, writing
tests, and documentation across all phases; all code and test results were reviewed and verified by running the
suite and builds. At *runtime* the system is AI-optional: the bundled `sample` provider is deterministic, and the
four demo verdict shapes are reproducible without any external API.

Detailed design, alternatives, and the failure analysis are maintained in a local-only `docs/` folder
(ARCHITECTURE.md, DATA_MODEL.md, API.md, DECISIONS.md, EVALUATION.md, FAILURE_ANALYSIS.md, LEARNING_NOTES.md,
INTERVIEW_PREP.md) and are intentionally excluded from this repository.

## Limitations and Next Steps

**Limitations**

- Free-tier Gemini rate limits; tests and the default demo use `sample` mode to avoid live-token cost.
- Scanned (image-only) pages cannot be text-extracted reliably (no OCR).
- Multi-period table extraction (Case 4) is a known, deliberately `UNCERTAIN` failure mode.
- Batch processing is in-process/async; no external task queue.
- The 3% value tolerance is fixed, and confidence is not calibrated against a large corpus (4 demo cases).
- The L1 reasoner does not read `scope`/`geography` (Consolidated vs Standalone pairs are not separated).
- No currency conversion or metric-synonym resolution; no upload-content deduplication.

**Next steps**

- OCR for scanned pages and per-fact salvage instead of all-or-nothing page validation.
- A scope/geography-aware comparability gate; currency + metric-synonym resolution.
- Calibrate tolerance/confidence on a larger corpus; move the pipeline onto a real task queue (Celery/Redis).
- Content dedup on upload and pagination for large fact/relationship listings.
- Run the six starter PDFs through live Gemini extraction so all four cases resolve on the real corpus.

## Additional Notes

- Results contain, per document: extracted **facts** with value/unit/period, **source evidence** (page + block), and
  **cross-document relationships** with verdict, confidence, and a human-readable reason.
- The four required cases are defined in `backend/app/evaluation/cases.py` — used by both the registration script and
  the test suite so the harness cannot drift from the definitions. Sample mode resolves **case 2** (contradiction)
  live against its synthetic fixture; **cases 1 (corroborate), 3 (resolved), and 4 (uncertain)** need the cleaner
  facts that Gemini extraction produces and are instead proven deterministically by
  `backend/tests/test_evaluation.py` and `test_reasoning.py` (all four verdict shapes).
- `data_mode` (`sample` / `live-llm` / `fixture`) is stamped on every document so sample and live corpora are never
  silently conflated in the UI.
- Structure: `backend/app/` — FastAPI + async SQLAlchemy; `frontend/src/` — React (Vite) SPA; `backend/tests/` —
  suite against a real PostgreSQL test database (`94 passed`).
- **No credentials are in this repository** — `.env.example` contains placeholders only; `.env` is gitignored.