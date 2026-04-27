-- Runs on first container init (empty volume only).
-- Ensures pgvector is available in the default database.
CREATE EXTENSION IF NOT EXISTS vector;
