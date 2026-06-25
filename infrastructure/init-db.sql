-- Vantage DB init — run once on fresh PostgreSQL
-- docker-entrypoint runs this automatically on first start

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- For fuzzy text search

-- Create application role with minimal permissions (no DELETE on audit_log)
-- ⚠️  LOCAL DEV ONLY — this file is NEVER run in production.
-- Production uses Azure Database for PostgreSQL with managed identity.
-- The password below is intentionally weak — only used in Docker Compose on localhost.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vantage_app') THEN
        CREATE ROLE vantage_app LOGIN PASSWORD 'vantage_app_local';
    END IF;
END$$;

GRANT CONNECT ON DATABASE vantage TO vantage_app;
GRANT USAGE ON SCHEMA public TO vantage_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO vantage_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO vantage_app;

-- audit_log is append-only — no UPDATE or DELETE for app role
REVOKE UPDATE ON audit_log FROM vantage_app;
REVOKE DELETE ON audit_log FROM vantage_app;
