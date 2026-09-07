-- PostgreSQL init script for Fact Knowledge Layer
-- Runs once on first container start (via docker-entrypoint-initdb.d).
-- Sets up the pgvector extension (idempotent checks are safe).

CREATE EXTENSION IF NOT EXISTS vector;

-- The application creates and manages its own tables via SQLAlchemy.
-- This file exists to ensure pgvector is available and to document
-- the expected extension. Runtime schema is applied by the backend
-- (backend/db/schema.py) so it can also run outside Docker.
