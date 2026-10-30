# Database setup

The app reads four tables in schema `cohort`, through a role that can do
nothing else. Run these steps as the database owner (the Northflank addon's
admin user, for example). Nothing below puts a password in a file.

## 1. Tables

```sh
psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 \
     -c "CREATE SCHEMA IF NOT EXISTS cohort" \
     -c "SET search_path TO cohort" \
     -f backend/db/schema.sql
```

`schema.sql` creates `master_patient`, `chronic_conditions`, `ed_episodes`
and `program_members`, with the indexes the queries use. It is safe to run
again. `backend/config/mapping.yaml` binds these tables and columns to the
roles the engine uses; to read different tables, change the mapping, not
the code.

## 2. The app's role

```sh
psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 \
     -v app_user=cohort_app -v app_password="$APP_DB_PASSWORD" \
     -v db_name=cohort -v data_schema=cohort \
     -f backend/db/roles.sql
```

`roles.sql` creates (or updates) `cohort_app` with:

- `LOGIN`, but not superuser and unable to create databases or roles;
- `CONNECT` on the database, `USAGE` on schema `cohort`, `SELECT` on its
  tables (including tables created later), and nothing on `public`;
- `default_transaction_read_only = on`, so even a mistaken query cannot write.

Give the backend `DB_USER=cohort_app` and `DB_PASSWORD` (or a `DATABASE_URL`
for that role). Never give it the owner's credentials.

## 3. Data

Synthetic data, with a known programme effect:

```sh
SEED_DATABASE_URL="$OWNER_DATABASE_URL" python -m app.seed --patients 20000 --seed 7
```

Your own extracts, one CSV per table named after it
(`master_patient.csv`, ...; columns as in `schema.sql`):

```sh
SEED_DATABASE_URL="$OWNER_DATABASE_URL" python -m app.seed --csv path/to/exports/
```

Loading replaces a table's contents, in one transaction. `--if-empty` skips
the load when data is already there (the compose file uses it). IDs are kept
as text, so leading zeros survive.

Set each source's `coverage` in `mapping.yaml` to the dates the extract is
complete for: patients whose windows fall outside it are excluded, because
missing data would otherwise read as "no events".

## Local mock database

`docker compose up` runs `postgres:latest`, and on first start
`backend/db/docker/init-db.sh` applies steps 1 and 2 and creates an empty
`cohort_test` database; the `seed` service then loads synthetic data. To
start again from nothing: `docker compose down -v`.

## Backend tests

The repository and API tests that need a database load small datasets into
throwaway schemas and drop them afterwards. They need a role that can create
schemas, which the compose owner can:

```sh
docker compose up -d postgres
cd backend
TEST_DATABASE_URL=postgresql://cohort_owner:local-owner-password@localhost:5433/cohort_test \
  uv run pytest
```

Without `TEST_DATABASE_URL` those tests are skipped and the rest still run.
