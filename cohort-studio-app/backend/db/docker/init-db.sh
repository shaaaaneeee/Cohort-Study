#!/bin/sh
# Local mock database only (docker-compose.yml). Runs once, when the Postgres
# volume is first created: the cohort schema and tables, the app's read-only
# role, and an empty database for the backend tests.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -c "CREATE SCHEMA IF NOT EXISTS cohort" \
     -c "SET search_path TO cohort" \
     -f /cohort-db/schema.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_user="${APP_DB_USER:-cohort_app}" \
     -v app_password="$APP_DB_PASSWORD" \
     -v db_name="$POSTGRES_DB" \
     -v data_schema=cohort \
     -f /cohort-db/roles.sql

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -c "CREATE DATABASE cohort_test OWNER \"$POSTGRES_USER\""
