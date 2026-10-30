# Architecture

Cohort Studio is two services and a database:

```
 browser ──HTTPS──▶ frontend (node:26.12.1, `serve`)      static React app + /config.js
    │
    └──HTTPS (CORS)──▶ backend (airbase python-3.13, FastAPI)
                          │  read-only role, parameterised SQL
                          ├──────────▶ PostgreSQL (schema "cohort")
                          └──HTTPS──▶ LLM provider (optional; demo script without a key)
```

The browser loads the app from the frontend service and calls the backend
directly; the frontend service never proxies API calls. The backend is the
only thing that talks to the database and to the language model.

## Frontend (`frontend/`)

React 19, TypeScript (strict), Vite, MUI. Layout:

| Path | What it holds |
|---|---|
| `src/api/` | `client.ts`: the one typed HTTP client; every failure becomes an `ApiError` with the backend's issues. `context.tsx` hands the client to components (tests pass a fake). |
| `src/store/studyStore.ts` | The single Zustand store. `study` is a `StudySpec`, exactly the backend's format. |
| `src/types/` | `openapi.ts` is generated from the backend's OpenAPI document (`npm run gen:types`); `index.ts` names the types. |
| `src/features/chat/` | Step 0, "Ask": the conversation and the drafted-study card. |
| `src/features/cohort-builder/` | Steps 1 and 2: cohort, covariates, outcome, and the feature dialog. |
| `src/features/results/` | Step 3: estimate, warnings, balance, and charts (MUI X Charts). |
| `src/components/` | Header, step tabs, sidebar (design check, Run), issue list, value pickers. |
| `src/hooks/` | `useStudyCheck` re-checks and recounts after every change; `useDimensionValues` loads filter values. |
| `src/config.ts` | Reads `window.__APP_CONFIG__` from `/config.js`. |

### One store, two writers

The cohort builder and the chat both read and write only `useStudyStore`:

1. **Manual change** (exposure, ages, filters, a feature): an action such as
   `setAgeRange` replaces `study` and bumps `revision`.
2. **Every chat turn** sends the conversation plus the current `study` as
   `draft`, so the assistant refines what the user sees, manual edits
   included. An untouched study is sent as `null`, so a first question is
   not read as "refine this empty study".
3. **The assistant's draft** comes back from `/api/chat`, is checked by
   `checkDraft` (shape, and names the metadata offers), and replaces `study`
   through `applyAssistantDraft`. Every control is bound to the store, so
   they show the draft at once, with no reload.
4. Any change to `study` triggers `useStudyCheck`, which re-runs
   `/api/study/check` and `/api/attrition` (latest request wins), so the
   sidebar, counts and model always describe the study on screen.

The study is also kept in `localStorage` so a refresh does not lose work.

### Runtime configuration

Vite bakes `import.meta.env` in at build time. To use one image in every
Northflank environment, `index.html` loads `/config.js` before the app, and
`docker-entrypoint.sh` writes that file from `API_BASE_URL` and `API_KEY` each
time the container starts. `serve.json` marks it `no-store`.

## Backend (`backend/`)

FastAPI on Python 3.13. Routes are thin; logic lives in services.

| Path | What it holds |
|---|---|
| `app/main.py` | `create_app()`: settings, logging, CORS, error handlers, routers. |
| `app/core/` | `config.py` (pydantic-settings, env only), `logs.py` (JSON logs, request ids), `errors.py` (one error shape), `mapping.py` (the dataset mapping), `exceptions.py`. |
| `app/api/routes/` | `metadata`, `study` (check, attrition, preview, analysis), `chat`, `health`. |
| `app/services/` | `study.py` (StudyService), `assistant.py` (one assistant turn), `catalogue.py`. |
| `app/schemas/` | `study.py` (StudySpec, FeatureSpec: the study format, unchanged from the POC), `api.py` (request and response bodies). |
| `app/db/` | `dialect.py` (PostgreSQL SQL fragments), `queries.py` (the SQL builder), `session.py` (engine, query runner), `repositories/cohort.py`. |
| `app/analysis/` | `validation.py` (design rules), `matching.py`, `outcome_models.py` (statistical models: CIs, p-values; renamed from `models.py` so it is not mistaken for DB models), `runner.py`. |
| `app/ai/` | `llm/` (provider-agnostic interface, Claude client, scripted and demo clients, factory), `tools.py`, `prompt.py`, `demo/` (the three scripted scenarios). |
| `app/seed/` | Synthetic data generator and the PostgreSQL loader (`python -m app.seed`). |
| `config/mapping.yaml` | Binds physical tables and columns to the roles the engine uses. Not secret; no connection settings. |
| `db/` | `schema.sql`, `roles.sql`, and the compose init script. |

### Endpoints

| Endpoint | Purpose |
|---|---|
| `GET /health` | 200 when the API is up and the database answers `SELECT 1`; 503 otherwise. No API key needed. |
| `GET /api/metadata` | Exposures, sources, dimensions, measures and aggregations the builder can offer. |
| `GET /api/values/{source}/{dimension}` | Values of a dimension (`person` for person attributes). |
| `POST /api/study/check` | Design issues and the implied model, without touching the cohort. |
| `POST /api/attrition` | Patients left after each eligibility step, by group. |
| `POST /api/preview` | One feature's values in the cohort, by group. |
| `POST /api/analysis` | Matching, balance, the effect estimate and every warning. |
| `POST /api/chat` | One assistant turn: `{messages, draft}` in; reply, questions, draft and issues out. |

Interactive docs are at `/docs`. Every error has the shape
`{"message": ..., "issues": [{"level", "code", "message", "feature"}]}`:
401 (bad API key), 404 (unknown name), 422 (invalid or unsound study, data
that cannot support the analysis), 503 (database or model unreachable), 500
(anything else; details only in the log).

### Data access and safety

- The SQL builder only writes names that were checked twice: against the
  mapping (`validate_study`) and against a plain-identifier pattern. Every
  user value (filter values, thresholds, dates) is a bound parameter.
- The app connects as a role that can only `SELECT` from schema `cohort`, and
  every session also sets `default_transaction_read_only=on`.
- Rows are ordered by byte value (`COLLATE "C"`) wherever order affects
  matching, so results do not depend on the server's locale.
- Controls draw their index date with the same md5 formula the POC used on
  DuckDB, so the same data and seed give the same cohort.

### The study assistant

Unchanged in behaviour from the POC. The model only proposes; every proposal
goes through the same `StudySpec` schema and `validate_study` rules as a
study built by hand, errors go back to the model, and nothing runs until the
user presses Run analysis. Tools and their JSON schemas are identical:

| Tool | What happens |
|---|---|
| `propose_study` | The whole study as JSON (schema: `StudySpec`). Validated; issues go back to the model. Without errors it becomes the draft. |
| `list_values` | All values of one dimension. |
| `ask_user` | Ends the turn with up to four questions. |
| `report_unsupported` | Ends the turn saying what the data lacks. |

`LLMClient` is a one-method interface (`step`); `AnthropicClient` uses Claude
with the server-side refusal fallback enabled. Without `LLM_API_KEY` the
backend uses `DemoClient`, which replays the three scripted scenarios
(complete, ambiguous, unsupported), so the app runs with no key. Another
provider is one more class and one branch in `app/ai/llm/factory.py`.

## What changed from the POC

| POC (`legacy/`) | Now |
|---|---|
| DuckDB file, loaded from CSV | PostgreSQL via SQLAlchemy 2 + psycopg 3, read-only role |
| `api.py` serving `web/` | Separate backend (API only) and frontend services |
| Plain JS, Chart.js from a CDN | React + MUI + MUI X Charts, typed against the backend schema |
| "Review in builder" copied the draft into the builder | Drafts apply to the one store at once; the builder sends its study with every chat turn |
| `COHORT_LLM*` variables; error without a key | `LLM_*` variables; demo when no key is set |
| Localhost only, no CORS | CORS from env, optional API key, `/health`, JSON logs |
