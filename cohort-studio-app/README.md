# Cohort Studio MCP server

Study tools for AI agents. An agent such as Genie One, Genie Code or the
Databricks AI Playground connects over MCP and can design and run an
observational cohort study: does an exposure (a programme) change an outcome
(ED attendances)? The agent handles the conversation; every number comes from
this server's tested code (propensity score matching, then the outcome model
the outcome type calls for). The agent never writes SQL and never sees
patient-level rows.

## The tools

| Tool | What it does |
|---|---|
| `describe_data` | What the data holds: exposures, sources, filters, and the study JSON schema |
| `list_values` | The allowed values of one filter, e.g. triage levels |
| `review_study` | What a draft still leaves open (outcome, follow-up, covariates, population), as questions with options for the agent to ask the user |
| `check_study` | Validates a study: design issues, patient counts per eligibility step, a plain-English summary and a confirmation code |
| `run_study` | Runs the analysis, only with the confirmation code of the study the user confirmed |

The server instructions tell the agent the order: describe, review, ask the
user, check and confirm, then run.

## How a call flows

```
agent ── MCP ──> app/mcp_server.py            the five tools
                 app/services/study.py        StudyService: check, attrition, analysis
                 app/services/clarify.py      open questions, summary, confirmation code
                 app/analysis/validation.py   design rules and cohort size
                 app/db/queries.py            SQL generation (names from the mapping, values bound)
                 app/db/dialect.py            Databricks SQL (or PostgreSQL locally)
                 app/db/databricks.py         SQL warehouse runner
                 app/analysis/                matching and outcome models
```

## Layout

| Path | What it is |
|---|---|
| `backend/app/` | The server (Python, FastAPI + MCP) |
| `backend/app.yaml` | The Databricks App's start command and settings |
| `backend/config/mapping.databricks.yaml` | The tables in Unity Catalog (`workspace.cohort.*`) |
| `backend/config/mapping.yaml` | The same tables in PostgreSQL, for local runs and tests |
| `backend/app/seed/` | The synthetic test data, and loading it into PostgreSQL |
| `backend/tests/` | Tests (PostgreSQL) |
| `docs/databricks-app.md` | Deploying on Databricks and connecting agents |

## Develop locally

```sh
cd backend
uv sync
TEST_DATABASE_URL=postgresql://user:pass@localhost/cohort_test uv run pytest
```

All data is synthetic. The earlier web app and study assistant are kept on the
`archive/web-app-and-assistant` branch.
