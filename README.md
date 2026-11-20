# Cohort Study

Cohort Studio: an AI-assisted tool for observational cohort studies on health
data. A researcher asks a question in plain words or builds the study step by
step (programme, population, covariates, outcome). The app builds the cohort
from the database, matches each programme member to a similar non-member, and
fits the model the outcome calls for. The AI only drafts the study definition;
every number comes from tested backend code.

| Path | What it is |
|---|---|
| [`cohort-studio-app/`](cohort-studio-app/) | **The application.** React frontend, FastAPI backend, PostgreSQL. Start with its [README](cohort-studio-app/README.md). |
| [`cohort-studio-app/docs/`](cohort-studio-app/docs/) | Architecture, deployment, database setup, and running the backend as a Databricks App |
| [`legacy/`](legacy/) | The original proof of concept (DuckDB, plain HTML), kept unchanged for reference |

## Where things are

| Part | Location |
|---|---|
| Study assistant (prompt, tools, model clients) | `cohort-studio-app/backend/app/ai/` |
| Study rules and checks | `cohort-studio-app/backend/app/analysis/validation.py` |
| SQL generation | `cohort-studio-app/backend/app/db/queries.py`, `dialect.py` |
| Matching and outcome models | `cohort-studio-app/backend/app/analysis/` |
| API routes | `cohort-studio-app/backend/app/api/routes/` |
| MCP server for AI agents (four study tools) | `cohort-studio-app/backend/app/mcp_server.py` |
| Databricks App setup | `cohort-studio-app/backend/app.yaml`, [docs/databricks-app.md](cohort-studio-app/docs/databricks-app.md) |
| Table mapping (PostgreSQL and Databricks) | `cohort-studio-app/backend/config/mapping*.yaml` |
| Frontend | `cohort-studio-app/frontend/src/` |

## Quick start

```sh
cd cohort-studio-app
docker compose up --build
```

Web app at http://localhost:8080, API docs at http://localhost:8000/docs.
All data is synthetic. Without an LLM key the assistant runs scripted demo
scenarios.
