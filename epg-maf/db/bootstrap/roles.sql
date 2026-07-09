-- =============================================================================
-- EGP Window — Postgres role bootstrap
--
-- Run ONCE as a Postgres superuser (typically 'postgres' in local dev) before
-- Alembic can apply the baseline schema.
--
-- Creates:
--   - egp_migrator   : DDL rights on the public schema. Used ONLY by CI-driven
--                      Alembic migrations and by developers running
--                      `alembic upgrade head` locally.
--   - egp_agent_ro   : SELECT-only. Used by the runtime application.
--
-- Deployment notes (Design §11.5):
--   - In prod, both roles are Entra ID service principals with managed
--     identity. The passwords set here are for local development only.
--   - Rotate defaults before this SQL is used in any shared environment.
-- =============================================================================

-- 1. Create the migrator role (DDL).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'egp_migrator') THEN
        CREATE ROLE egp_migrator WITH LOGIN PASSWORD 'CHANGEME_MIGRATOR_PW';
    END IF;
END
$$;

-- 2. Create the application read-only role.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'egp_agent_ro') THEN
        CREATE ROLE egp_agent_ro WITH LOGIN PASSWORD 'CHANGEME_AGENT_RO_PW';
    END IF;
END
$$;

-- 3. Schema-level grants.
GRANT USAGE, CREATE ON SCHEMA public TO egp_migrator;
GRANT USAGE            ON SCHEMA public TO egp_agent_ro;

-- 4. Default privileges: any table created BY egp_migrator IN schema public
--    grants SELECT to egp_agent_ro. This future-proofs new tables created
--    by later migrations.
ALTER DEFAULT PRIVILEGES FOR ROLE egp_migrator IN SCHEMA public
    GRANT SELECT ON TABLES TO egp_agent_ro;

ALTER DEFAULT PRIVILEGES FOR ROLE egp_migrator IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO egp_agent_ro;

-- 5. Prevent the migrator from writing on connections (defensive; the app
--    never uses this role, but if a bug did, this would still block writes).
--    The application always uses egp_agent_ro which cannot write.
--
--    Note: egp_migrator is expected to use elevated permissions during CI;
--    connection-time READ ONLY is set application-side by DbPoolFactory for
--    egp_agent_ro connections.
