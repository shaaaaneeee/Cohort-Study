# Running the backend as a Databricks App (MCP for Genie Code)

Genie Code cannot reach the Northflank service (the government network blocks
it), so the same backend runs inside Databricks instead: a Databricks App built
from this repository's `backend/` folder. It reads the copy of the tables in
Unity Catalog (`workspace.cohort.*`) through a SQL warehouse, and serves the
study tools (`describe_data`, `list_values`, `check_study`, `run_study`) over
MCP at `/mcp`. The web app and the LLM are not used there.

What makes this work:

- `backend/app.yaml`: the start command and settings for the App.
- `config/mapping.databricks.yaml`: the same mapping with `dialect: databricks`
  and `workspace.cohort.*` tables.
- `app/db/dialect.py` (`DatabricksDialect`) and `app/db/databricks.py`: the date
  functions and the query runner for a SQL warehouse. A full study run on Spark
  SQL and on PostgreSQL with the same data gives identical results.
- No `requirements.txt` in `backend/` (the Docker image uses
  `requirements.lock.txt`): with one, Databricks would install with Python 3.11,
  which the pinned packages do not support. Without it, Databricks installs from
  `pyproject.toml` + `uv.lock` with Python 3.13.
- `MCP_PLATFORM_AUTH=true`: Databricks signs every caller in before a request
  reaches the app, so `/mcp` needs no token of its own there.

## Steps

1. **Pull the repo into Databricks.** Workspace → your folder → Create → Git
   folder → the GitHub URL, branch `main`.
   A private repo needs GitHub linked under Settings → Linked accounts.
2. **Create the app.** Compute → Apps → Create app → Custom. Name it
   `mcp-cohort-study`: the name must start with `mcp-` for Databricks to list it
   as an MCP server. Under App resources add a **SQL warehouse** (the
   Serverless Starter Warehouse), permission *Can use*, resource key
   `sql-warehouse`. Create.
3. **Let the app read the tables.** On the app's page, Authorization tab, copy
   the service principal's name or ID. In the SQL editor:

   ```sql
   GRANT USE CATALOG ON CATALOG workspace TO `<service principal ID>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.cohort TO `<service principal ID>`;
   ```

4. **Deploy.** App page → Deploy → source folder
   `/Workspace/Users/<you>/<git folder>/cohort-studio-app/backend`. When it shows
   *Running*, the Logs tab should end with `Uvicorn running`.
5. **Allow the workspace in CORS.** Set `CORS_ORIGINS` in `app.yaml` to the
   workspace URL (Genie Code calls `/mcp` from the browser), then deploy again.
6. **Connect an agent.**
   - Genie Code: settings → Customizations → Connectors → Add MCP server →
     Custom MCP server → `mcp-cohort-study` → Save.
   - AI Playground: Tools → Add tool → MCP Servers → Custom MCP Server →
     `mcp-cohort-study`.

   Ask something vague such as "Does Programme A help patients?": the agent
   should call `review_study` and ask you before it runs anything.

To update after a code change: pull in the Git folder, then Deploy again.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Deploy fails installing packages | A `requirements.txt` crept into `backend/`; remove it. |
| Tools answer "No Databricks credentials" | Not running as an App, or the app has no service principal yet. |
| Tools answer "SQL warehouse could not run the query" | Missing grants (step 3), or the warehouse resource key is not `sql-warehouse`. |
| "DATABRICKS_WAREHOUSE_ID is not set" | The SQL warehouse resource was not added (step 2). |
