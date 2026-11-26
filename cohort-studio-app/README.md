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
agent ── MCP ──> app/mcp_protocol.py          MCP over HTTP (JSON-RPC), no extra package
                 app/mcp_server.py            the five tools
                 app/services/study.py        StudyService: check, attrition, analysis
                 app/services/clarify.py      open questions, summary, confirmation code
                 app/analysis/validation.py   design rules and cohort size
                 app/db/queries.py            SQL generation (names from the mapping, values bound)
                 app/db/dialect.py            Databricks SQL date functions
                 app/db/databricks.py         SQL warehouse runner
                 app/analysis/                matching and outcome models
```

## Layout

| Path | What it is |
|---|---|
| `backend/app/` | The server (Python 3.11+, FastAPI) |
| `backend/app.yaml` | The Databricks App's start command and settings |
| `backend/requirements.txt` | The packages, installed by Databricks with pip |
| `backend/config/mapping.yaml` | The tables in Unity Catalog (`workspace.cohort.*` by default) |
| `backend/app/seed/synthetic.py` | The synthetic data: a planted effect (rate ratio 0.70) and a planted selection bias |
| `notebooks/load_synthetic_data.py` | Databricks notebook that writes the synthetic tables into a catalog and schema |
| `docs/databricks-app.md` | Loading the data, deploying, connecting agents, moving to Healix |
| `docs/genie-evaluation.md` | How Genie One uses the tools, before and after the fixes |

Lines that change in another workspace (e.g. Healix) are marked `HEALIX`.

## Try it in a new workspace

1. Pull this repo as a Git folder.
2. Run `notebooks/load_synthetic_data.py` (set the catalog and schema widgets).
3. Deploy `backend/` as a Databricks App: [docs/databricks-app.md](docs/databricks-app.md).

## Checks before merging

```sh
cd backend
pip install -r requirements.txt ruff mypy pandas-stubs types-PyYAML scipy-stubs
ruff check . && ruff format --check . && mypy
```

Settings are in `ruff.toml` and `mypy.ini`.

All data is synthetic. Earlier versions are kept on branches:
`archive/web-app-and-assistant` (the web app and its study assistant) and
`archive/mcp-with-postgres-tests` (PostgreSQL support and the test suite).
