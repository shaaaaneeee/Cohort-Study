# cohort-studio

A cohort study platform for health data. A researcher defines a treatment
group, control group, covariates and an outcome; the system builds an
analysis-ready table from a SQL database, balances the groups and fits the
model the outcome calls for. A study can also be described in plain words:
an assistant drafts it, and the researcher reviews it before anything runs.

Status: phase 5 of 6. Mapping config, study schema, design validator, a
DuckDB backend that builds the analysis-ready table, the statistics
(propensity score matching, balance, outcome models), the HTTP API and the
study builder in the browser. Databricks is next.

## Setup

Python 3.11 or later.

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -r requirements.txt
    python -m pytest

## Data

Load your own CSV or Parquet files. Each file is named after its table
(`master_patient`, `chronic_conditions`, `ed_episodes`, `program_members`;
columns as in `cohort_studio/ddl.sql`):

    python -m cohort_studio.loader data/cohort.duckdb path/to/exports/

Or generate synthetic data with a known effect and load that:

    python -m cohort_studio.synthetic data/synthetic
    python -m cohort_studio.loader data/cohort.duckdb data/synthetic/

`config/mapping.yaml` points at `data/cohort.duckdb`. Set each source's
`coverage` to the dates your extract is complete for.

## Running it

    python -m cohort_studio.api

Then open http://127.0.0.1:8765 for the study builder. Set `PORT` to change
the port and `COHORT_CONFIG` to use another mapping file. The API's own
documentation is at `/docs`. It listens on this computer only, because there
is no authentication yet. The pages load Chart.js from a CDN, so the browser
needs internet access.

| Endpoint | Purpose |
|---|---|
| `GET /api/metadata` | Exposures, sources, dimensions, measures and aggregations the builder can offer. |
| `GET /api/values/{source}/{dimension}` | Values of a dimension (`person` for person attributes). |
| `POST /api/study/check` | Design issues and the model the outcome implies, without touching the cohort. |
| `POST /api/attrition` | Patients left after each eligibility step, by group. |
| `POST /api/preview` | One feature's values in the cohort, by group. Body: `{"feature": ..., "study": ...}`. |
| `POST /api/analysis` | Matching, balance, the effect estimate and every warning. |
| `POST /api/chat` | One turn with the study assistant. Body: `{"messages": [...], "draft": study or null}`. Returns the reply, any questions, and the drafted study with its issues. |

## The study assistant

The Ask tab (step 0) takes a research question in plain words. The
assistant asks about anything that is missing, drafts the study, and hands
it to the builder for review. The language model only drafts the study: every
draft passes the same schema and design checks as one built by hand, and the
analysis runs only when the user clicks Run analysis. See
`docs/architecture.md`.

It uses Claude through the `anthropic` package. Set your API key before
starting the server:

    set ANTHROPIC_API_KEY=...          (Windows; export on macOS and Linux)
    python -m cohort_studio.api

| Variable | Default | Purpose |
|---|---|---|
| `COHORT_LLM` | `anthropic` | `demo` plays the three demonstration scenarios with no key: ask about ED visits, about mortality, or whether the programme "helps". `scripted` replays one script file |
| `COHORT_LLM_SCRIPT` | | The script file for `scripted`, such as `examples/assistant/scenario_a_complete.json` |
| `COHORT_LLM_MODEL` | `claude-opus-5-5` | The Claude model |
| `COHORT_LLM_EFFORT` | `medium` | How much the model thinks: `low`, `medium`, `high`, `xhigh` or `max` |

`examples/assistant/` has scripts for the three demonstration scenarios: a
complete question, an ambiguous one and an unsupported one. To try them
without a key:

    set COHORT_LLM=demo
    python -m cohort_studio.api

## Layout

| Path | Purpose |
|---|---|
| `config/mapping.yaml` | Binds physical tables and columns to the logical roles the engine uses, and names the database. |
| `cohort_studio/mapping.py` | Loads the mapping and refuses any table or column name that is not a plain identifier. |
| `cohort_studio/features.py` | Schema for features (covariates, outcomes, inclusion criteria) and for a study. Window semantics are documented on `Window`. |
| `cohort_studio/validator.py` | Rejects unsound designs (look-ahead, outcome reused as covariate, windows finer than the data, post-index inclusion) and warns about weak ones. |
| `cohort_studio/sql.py` | Turns a study into SQL: one CTE per feature, the cohort LEFT JOINed to all of them. |
| `cohort_studio/dialect.py` | The date arithmetic and other SQL that differs between engines. |
| `cohort_studio/repository.py` | The `CohortRepository` interface and its SQL implementation. |
| `cohort_studio/ddl.sql`, `loader.py` | Table definitions and the CSV/Parquet loader. |
| `cohort_studio/synthetic.py` | Synthetic data with a planted programme effect and selection bias. |
| `cohort_studio/matching.py` | Covariates, propensity scores, 1:1 caliper matching and balance before and after. |
| `cohort_studio/models.py` | Which model an outcome calls for (known before any data is read) and fitting it. |
| `cohort_studio/analysis.py` | `run_analysis`: matching, model, warnings and a plain-English reading, from an analysis table. |
| `cohort_studio/llm.py` | The language model interface: Claude, or a scripted stand-in for tests and demos. |
| `cohort_studio/assistant.py` | `converse`: one turn of the study assistant, from question to validated draft. |
| `cohort_studio/api.py` | The HTTP API; also serves `web/`. |
| `web/` | The study builder: `chat.js` (the assistant), `app.js` (cohort and features), `results.js` (results and charts), `dom.js` (shared helpers). Plain HTML and JavaScript, no build step. |
| `examples/assistant/` | Scripted conversations for the three demonstration scenarios. |
| `docs/architecture.md` | How the assistant fits in front of the engine, and what the model may decide. |
| `tests/` | One test file per module. `test_repository.py` checks the analysis table value by value on hand-made data; `test_analysis.py` checks the planted effect is recovered end to end. |
