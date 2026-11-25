# Deploying the MCP server on Databricks

The server runs as a Databricks App built from `cohort-studio-app/backend`. It
reads the cohort tables in Unity Catalog (`workspace.cohort.*` by default)
through a SQL warehouse and serves the study tools at `/mcp`.

What makes this work:

- `backend/app.yaml`: the start command and settings for the App.
- `config/mapping.yaml`: the four tables, by full name (`catalog.schema.table`).
- `app/db/dialect.py` (`DatabricksDialect`) and `app/db/databricks.py`: the
  date functions and the query runner for a SQL warehouse.
- No `requirements.txt` in `backend/`: with one, Databricks would install with
  Python 3.11, which the pinned packages do not support. Without it, Databricks
  installs from `pyproject.toml` + `uv.lock` with Python 3.13.
- No token of our own: Databricks signs in every caller before a request
  reaches the app.

## 1. Deploy the app

1. **Pull the repo.** Workspace → your folder → Create → Git folder → the
   GitHub URL, branch `main`. A private repo needs GitHub linked under
   Settings → Linked accounts. To update later: open the Git folder → Pull.
2. **Load the data.** Open `cohort-studio-app/notebooks/load_synthetic_data.py`,
   set the `catalog` and `schema` widgets (default `workspace` / `cohort`) →
   Run all. It writes the four synthetic tables, replacing any already there.
   For another catalog or schema, change the `workspace.cohort.` prefix of the
   four tables in `backend/config/mapping.yaml` to match.
3. **Create the app.** Compute → Apps → Create app → Custom. Name it
   `mcp-cohort-study`: the name must start with `mcp-` for Databricks to list
   it as an MCP server. Under App resources add a **SQL warehouse**, permission
   *Can use*, resource key `sql-warehouse`.
4. **Let the app read the tables.** Copy the app's service principal ID
   (Authorization tab). In the SQL editor:

   ```sql
   GRANT USE CATALOG ON CATALOG workspace TO `<app service principal ID>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA workspace.cohort TO `<app service principal ID>`;
   ```

5. **Allow the workspace in CORS.** Set `CORS_ORIGINS` in `app.yaml` to the
   workspace URL (Genie Code calls `/mcp` from the browser).
6. **Deploy.** App page → Deploy → source folder
   `/Workspace/Users/<you>/<git folder>/cohort-studio-app/backend`. When it shows
   *Running*, the Logs tab ends with `Uvicorn running`. Free Edition stops idle
   apps: Start it again if a connection reports HTTP 503.

## 2. Connect an agent

**Genie Code** (and the AI Playground) can use the app directly:

- Genie Code: settings → Customizations → Connectors → Add MCP server →
  Custom MCP server → `mcp-cohort-study`.
- AI Playground: Tools → Add tool → MCP Servers → Custom MCP Server →
  `mcp-cohort-study`.

**Genie One** (and Genie Agents) need it registered in Unity Gateway first. The
automatic sign-in (DCR) does not work with Databricks Apps, so the connection
signs in as a service principal:

1. **A caller service principal.** Settings → Identity and access → Service
   principals → Add → `cohort-mcp-caller` (no admin access). Secrets →
   Generate secret: scope *Other APIs* → `all-apis` (read + write), lifetime no
   longer than needed. Copy the client ID and secret straight into step 3;
   never paste or save them anywhere else.
2. **Let it call the app.** Compute → Apps → `mcp-cohort-study` → Permissions →
   search by the service principal's application ID → **Can Use** (not Can
   Manage).
3. **Register the server.** AI Gateway → MCPs → + MCP → Connect an existing MCP
   server:
   - Server URL: `https://<app URL>/mcp`
   - Location: `workspace.cohort`, service name `mcp_cohort_study`
   - Authentication: **Application account (OAuth)**, the client ID and secret,
     token endpoint `https://<workspace URL>/oidc/v1/token`, scope `all-apis`
   - Tools: All tools → Create MCP Service
4. **Use it.** Genie One → Customizations → Connectors: the five tools appear.
   For a Genie Agent: Configure → Resources → Connectors → Add.

## 3. Test

Ask something vague, such as "Does Programme A help patients?". The agent
should call `describe_data` and `review_study`, ask the open questions, show
a summary to confirm, and only then call `run_study`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Deploy fails installing packages | A `requirements.txt` crept into `backend/`; remove it. |
| HTTP 503 "App Not Available" | The app is stopped (Free Edition stops idle apps): Start it. |
| HTTP 401 from Unity Gateway | The caller service principal lacks **Can Use** on the app. |
| "Failed to generate OAuth token" in an agent | The platform's sign-in between agent and app; retry, or reconnect the connector. |
| Tools answer "No Databricks credentials" | Not running as an App, or the app has no service principal yet. |
| Tools answer "SQL warehouse could not run the query" | Missing grants (deploy step 4), tables not loaded (step 2), the table names in `mapping.yaml` don't match the catalog and schema, or the warehouse resource key is not `sql-warehouse`. |
| "DATABRICKS_WAREHOUSE_ID is not set" | The SQL warehouse resource was not added (deploy step 3). |
