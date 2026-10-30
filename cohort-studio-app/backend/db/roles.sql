-- The app's database role: log in, read the cohort schema, nothing else.
--
-- Run as the database owner, with psql variables for the names and password,
-- so no secret is written into this file:
--
--   psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 \
--        -v app_user=cohort_app -v app_password="$APP_DB_PASSWORD" \
--        -v db_name=cohort -v data_schema=cohort -f db/roles.sql
--
-- Safe to run again: it updates the password and re-applies the grants.

SELECT format('CREATE ROLE %I LOGIN', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

-- Not a superuser, cannot create databases or roles, and does not inherit
-- privileges from other roles.
SELECT format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT '
              'NOREPLICATION CONNECTION LIMIT 20 PASSWORD %L',
              :'app_user', :'app_password') \gexec

-- Every transaction it starts is read-only, whatever the app asks for.
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'app_user') \gexec

SELECT format('CREATE SCHEMA IF NOT EXISTS %I', :'data_schema') \gexec

-- Nothing in the database by default, then exactly what it needs.
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db_name') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', :'db_name', :'app_user') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT USAGE ON SCHEMA %I TO %I', :'data_schema', :'app_user') \gexec
SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I',
              :'data_schema', :'app_user') \gexec
-- Tables the owner creates in the schema later are readable too.
SELECT format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO %I',
              :'data_schema', :'app_user') \gexec
