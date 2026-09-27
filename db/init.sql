-- Runs once, when the postgres volume is first created (docker-entrypoint-initdb.d), as the owner role
-- (POSTGRES_USER) in the POSTGRES_DB database.
--
-- Tables are NOT created here: the schema is owned by Alembic (backend/alembic). No extension is required —
-- a DBA-managed PostgreSQL 14 or newer with no contrib packages is enough (ADR 0007, docs/operations.md).
--
-- What it does create, when APP_DB_USER and APP_DB_PASSWORD are set in the postgres container's environment,
-- is the login role the API connects with: not a superuser, no DDL rights, and exactly the privileges the
-- endpoints need — SELECT on every table Alembic creates, INSERT on the three append-only tables, UPDATE on
-- api_keys (revocation and last_used_at). The owner role keeps everything else, so `alembic upgrade head`, the
-- seed loader and the ML pipelines are unaffected. Without those two variables nothing happens here and the API
-- keeps using the owner role, as the demo stack does (docs/security.md §2).
--
-- The privileges are applied by an event trigger because the tables do not exist yet at this point: it fires once
-- per CREATE TABLE in the public schema during the migration that follows and grants by table name.

\set hqai_app_user ''
\set hqai_app_password ''
\getenv hqai_app_user APP_DB_USER
\getenv hqai_app_password APP_DB_PASSWORD

CREATE OR REPLACE FUNCTION public.hqai_grant_app_privileges() RETURNS event_trigger LANGUAGE plpgsql AS $$
DECLARE
    app_role text := current_setting('hqai.app_role', true);
    created record;
    sequence_name text;
BEGIN
    IF app_role IS NULL OR app_role = '' THEN
        RETURN;
    END IF;
    FOR created IN
        SELECT object_identity FROM pg_event_trigger_ddl_commands()
        WHERE object_type = 'table' AND schema_name = 'public'
    LOOP
        IF created.object_identity = 'public.alembic_version' THEN
            CONTINUE;  -- migration bookkeeping belongs to the owner role only
        ELSIF created.object_identity IN ('public.access_log', 'public.decision_log', 'public.specialist_decision') THEN
            EXECUTE format('GRANT SELECT, INSERT ON TABLE %s TO %I', created.object_identity, app_role);
        ELSIF created.object_identity = 'public.api_keys' THEN
            EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE %s TO %I', created.object_identity, app_role);
        ELSE
            EXECUTE format('GRANT SELECT ON TABLE %s TO %I', created.object_identity, app_role);
            CONTINUE;  -- read tables need no sequence
        END IF;
        sequence_name := pg_get_serial_sequence(created.object_identity, 'id');
        IF sequence_name IS NOT NULL THEN
            EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO %I', sequence_name, app_role);
        END IF;
    END LOOP;
END;
$$;

DROP EVENT TRIGGER IF EXISTS hqai_grant_app_privileges;
CREATE EVENT TRIGGER hqai_grant_app_privileges ON ddl_command_end
    WHEN TAG IN ('CREATE TABLE')
    EXECUTE FUNCTION public.hqai_grant_app_privileges();

CREATE OR REPLACE FUNCTION pg_temp.hqai_create_app_role(app_role text, app_password text) RETURNS text LANGUAGE plpgsql AS $$
BEGIN
    IF app_role = '' OR app_password = '' THEN
        RETURN 'APP_DB_USER/APP_DB_PASSWORD not set: the API will connect with the owner role';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = app_role) THEN
        EXECUTE format(
            'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L',
            app_role, app_password
        );
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), app_role);
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', app_role);
    EXECUTE format('REVOKE CREATE ON SCHEMA public FROM %I', app_role);
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
    EXECUTE format('ALTER DATABASE %I SET hqai.app_role = %L', current_database(), app_role);
    RETURN format('role %I created: no DDL, SELECT on the read tables, INSERT on the audit tables', app_role);
END;
$$;

SELECT pg_temp.hqai_create_app_role(:'hqai_app_user', :'hqai_app_password') AS app_role;
