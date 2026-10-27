# Deploying to Northflank

Three pieces: a **backend** service, a **frontend** service, and a
**PostgreSQL** addon (or an existing database). Each service builds from its
own Dockerfile.

## Order

1. **PostgreSQL.** Create the addon (or point at an existing server). Set up
   the schema and the app's read-only role as in [db-setup.md](db-setup.md),
   then load data (`python -m app.seed` as a one-off job, or your own load).
2. **Backend service.** Build context `cohort-studio-app/backend`,
   Dockerfile `Dockerfile`. Port 8000 (HTTP, public). Health check:
   `GET /health`. Set the variables below; put passwords and keys in a
   secret group.
3. **Frontend service.** Build context `cohort-studio-app/frontend`,
   Dockerfile `Dockerfile`. Port 8080 (HTTP, public). Health check: `GET /`.
   Set `API_BASE_URL` to the backend's public URL.
4. Go back to the backend and set `CORS_ORIGINS` to the frontend's public
   URL. Without it the browser refuses the API's responses.

The backend image's base is
`registry.sgts.gitlab-dedicated.com/innersource/sgts/runtime/airbase/images/gdssingapore/airbase:python-3.13`;
Northflank needs pull credentials for that registry. The frontend uses
`node:26.12.1` from Docker Hub.

## Service dependencies

| Service | Needs | Why |
|---|---|---|
| frontend | backend's public URL | The browser calls the API directly. |
| backend | PostgreSQL | All data. `/health` reports 503 until it answers. |
| backend | LLM provider (optional) | The study assistant; without a key it plays the demo. |
| backend | frontend's public URL | `CORS_ORIGINS`. |

## Backend variables

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `production` | `development`, `test` or `production`. Logged at start-up. |
| `HOST` | `0.0.0.0` | Interface to listen on. |
| `PORT` | `8000` | Port to listen on. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `LOG_FORMAT` | `json` | `json` (one object per line, for log collectors) or `text`. |
| `CORS_ORIGINS` | *(none)* | Comma-separated browser origins allowed to call the API, e.g. `https://studio.example.org`. Empty means no browser access. |
| `API_KEY` | *(none)* | Optional. When set, `/api/*` needs `X-API-Key`. The frontend sends it, so anyone who can load the page can read it: it keeps out casual traffic and bots, not a determined user. For real access control put the services behind Northflank's private networking or an authenticating proxy. |
| `DATABASE_URL` | *(none)* | `postgresql://user:password@host:5432/db?sslmode=require`. Takes precedence over the `DB_*` variables. |
| `DB_HOST` | `localhost` | Database host. |
| `DB_PORT` | `5432` | Database port. |
| `DB_NAME` | `cohort` | Database name. |
| `DB_USER` | `cohort_app` | The app's read-only role. |
| `DB_PASSWORD` | *(none)* | Secret. |
| `DB_SSLMODE` | *(none)* | e.g. `require` for a managed database. |
| `DB_POOL_SIZE` | `5` | Connections kept open. |
| `DB_MAX_OVERFLOW` | `5` | Extra connections under load. |
| `DB_STATEMENT_TIMEOUT_MS` | `120000` | Longest a query may run. |
| `MAPPING_PATH` | `config/mapping.yaml` | The dataset mapping file. |
| `LLM_PROVIDER` | *(auto)* | `anthropic`, `demo` or `scripted`. Unset: `anthropic` when `LLM_API_KEY` is set, `demo` otherwise. |
| `LLM_API_KEY` | *(none)* | Secret. The model provider's key. |
| `LLM_BASE_URL` | *(provider default)* | Another endpoint for the provider, e.g. a gateway. |
| `LLM_MODEL` | `claude-opus-5-5` | Model id. |
| `LLM_EFFORT` | `medium` | `low`, `medium`, `high`, `xhigh`, `max`. |
| `LLM_TIMEOUT_SECONDS` | `120` | Per request to the model. |
| `LLM_SCRIPT` | *(none)* | Script file for `LLM_PROVIDER=scripted`. |

Seed job only: `SEED_DATABASE_URL` (an owner role) and optionally
`SEED_SCHEMA` (default `cohort`).

## Frontend variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | Port `serve` listens on. |
| `API_BASE_URL` | *(empty)* | The backend's public URL, without a trailing slash. Written to `/config.js` at start-up. |
| `API_KEY` | *(empty)* | Same value as the backend's `API_KEY`, if one is set. |

Changing these needs a restart, not a rebuild.

## Checks after deploying

- `GET https://<backend>/health` returns `{"status": "ok", "database": "ok"}`.
- `https://<frontend>/config.js` shows the backend URL.
- The app loads the dataset name in the header; the Cohort tab shows counts.
- Asking "Does Programme A reduce ED attendances?" drafts a study and fills
  the builder's controls.

## Images

Both run as non-root (`app` uid 999 for the backend, `node` uid 1000 for the
frontend), carry no secrets, install dependencies in their own cached layer
(backend: `requirements.txt` with hashes, exported from `uv.lock`; frontend:
`npm ci` from `package-lock.json`), and declare a `HEALTHCHECK`.
