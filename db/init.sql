-- Runs once, when the postgres volume is first created (docker-entrypoint-initdb.d).
-- Tables are NOT created here: the schema is owned by Alembic (backend/alembic).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
