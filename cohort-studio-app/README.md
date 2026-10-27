# Cohort Studio

A study-design assistant for health data. A researcher describes a cohort
study in plain words or builds it step by step (treatment group, inclusion
criteria, covariates, outcome); the app builds the cohort from PostgreSQL,
matches treated patients to controls, and fits the model the outcome calls
for.

| Path | What it is |
|---|---|
| `frontend/` | React + Vite + TypeScript + MUI web app (own Dockerfile) |
| `backend/` | FastAPI service: API, database access, statistics, study assistant (own Dockerfile) |
| `docs/` | [architecture](docs/architecture.md), [deployment](docs/deployment.md), [database setup](docs/db-setup.md) |
| `docker-compose.yml` | Local development: frontend, backend, and a seeded mock PostgreSQL |

The original proof of concept is in `../legacy/`, unchanged, for comparison.

## Run everything locally

Needs Docker.

```sh
cp .env.example .env        # optional
docker compose up --build
```

- Web app: http://localhost:8080
- API docs: http://localhost:8000/docs
- PostgreSQL: `localhost:5433` (owner `cohort_owner`)

Compose starts PostgreSQL, creates the schema and the app's read-only role,
loads 20,000 synthetic patients, then starts the backend and the frontend.
Without `LLM_API_KEY` the assistant plays three scripted scenarios: ask about
ED attendances, about mortality, or whether the programme "helps".

## Develop without Docker

Backend (Python 3.13, [uv](https://docs.astral.sh/uv/)):

```sh
cd backend
uv sync
cp .env.example .env        # point DB_* at a database; see docs/db-setup.md
uv run python -m app        # http://localhost:8000
```

Frontend (Node 24 or later):

```sh
cd frontend
npm ci
npm run dev                 # http://localhost:5173; public/config.js points at :8000
```

## Checks

```sh
cd backend
uv run ruff check . && uv run ruff format --check . && uv run mypy
TEST_DATABASE_URL=postgresql://cohort_owner:local-owner-password@localhost:5433/cohort_test uv run pytest

cd frontend
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

Backend tests that need PostgreSQL are skipped when `TEST_DATABASE_URL` is
not set; `docker compose up -d postgres` provides one.

After changing a backend request or response model, regenerate the
frontend's types:

```sh
cd backend && uv run python scripts/export_openapi.py ../frontend/openapi.json
cd ../frontend && npm run gen:types
```

## How the services connect

The browser loads the app from the frontend service and calls the backend
directly, at the URL in `/config.js` (written from `API_BASE_URL` when the
frontend container starts, so one image serves every environment). The
backend allows that origin through `CORS_ORIGINS`, reads PostgreSQL as a
read-only role, and calls the LLM provider for the assistant. Every
environment variable is listed in [docs/deployment.md](docs/deployment.md).
