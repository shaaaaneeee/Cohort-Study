# Deploying the MCP server on Databricks

The server runs as a Databricks App built from `cohort-studio-app/backend`. It
reads four Unity Catalog tables through a SQL warehouse and serves the study
tools at `/mcp`. Setup takes about 30 minutes: load the data, create and
deploy the app, connect an agent.

How it fits together:

| Piece | Where |
| --- | --- |
| Start command and settings | `backend/app.yaml` |
| Packages (pip, Python 3.11; no `mcp` package needed) | `backend/requirements.txt` |
| The four tables, by full name `catalog.schema.table` | `backend/config/mapping.yaml` |
| Databricks SQL and the warehouse runner | `app/db/dialect.py`, `app/db/databricks.py` |
| MCP over HTTP (JSON-RPC, stateless) | `app/mcp_protocol.py` |

The app holds no secrets: Databricks signs in every caller before a request
reaches it, and the app reads the tables as its own service principal.

## 1. Deploy the app

1. **Pull the repo.** Workspace → Create → Git folder → the GitHub URL,
   branch `main`. A private repo needs GitHub linked under Settings → Linked
   accounts. To update later: open the Git folder → Pull.
2. **Load the data.** Open `cohort-studio-app/notebooks/load_synthetic_data.py`,
   set the `catalog` and `schema` widgets (default `workspace` / `cohort`), and
   Run all. It writes the four synthetic tables, replacing any already there.
   For another catalog or schema, change the `workspace.cohort.` prefix of the
   four tables in `backend/config/mapping.yaml` to match.
3. **Create the app.** Compute → Apps → Create app → Custom. The name must
   start with `mcp-` (e.g. `mcp-cohort-study`) for Databricks to list it as an
   MCP server. Under App resources add a **SQL warehouse**, permission
   *Can use*, resource key `sql-warehouse` exactly.
4. **Let the app read the tables.** Copy the app's service principal ID
   (Authorization tab). In the SQL editor:

   ```sql
   GRANT USE CATALOG ON CATALOG <catalog> TO `<app service principal ID>`;
   GRANT USE SCHEMA, SELECT ON SCHEMA <catalog>.<schema> TO `<app service principal ID>`;
   ```

5. **Allow the workspace in CORS.** Set `CORS_ORIGINS` in `app.yaml` to the
   workspace URL, no trailing slash. Genie Code calls `/mcp` from the browser.
6. **Deploy.** App page → Deploy → source folder
   `/Workspace/Users/<you>/<git folder>/cohort-studio-app/backend`. It is up
   when it shows *Running* and the Logs tab ends with `Uvicorn running`.

## 2. Connect an agent

**Genie Code and the AI Playground** connect directly, with the user's own
sign-in:

- Genie Code: settings → Customizations → Connectors → Add MCP server →
  Custom MCP server → the app.
- AI Playground: Tools → Add tool → MCP Servers → Custom MCP Server → the app.

**Genie One and Genie Agents** need the app registered in Unity Gateway. Their
automatic sign-in (dynamic client registration) does not work with Databricks
Apps, so the connection signs in as a dedicated service principal:

1. **Create the caller.** Settings → Identity and access → Service principals →
   Add, e.g. `cohort-mcp-caller`, no admin rights. Secrets → Generate secret:
   scope `all-apis`, lifetime no longer than needed. Copy the client ID and
   secret straight into step 3; never paste or save them anywhere else.
2. **Let it call the app.** Apps → the app → Permissions → search by the
   principal's application ID (it may not show by name) → **Can Use**, not
   Can Manage.
3. **Register the server.** AI Gateway → MCPs → + MCP → Connect an existing MCP
   server:

   | Field | Value |
   | --- | --- |
   | Server URL | `https://<app URL>/mcp` |
   | Location | `<catalog>.<schema>`, service name e.g. `mcp_cohort_study` |
   | Authentication | Application account (OAuth): the client ID and secret |
   | Token endpoint | `https://<workspace URL>/oidc/v1/token` |
   | Scope | `all-apis` |
   | Tools | All tools |

4. **Use it.** Genie One → Customizations → Connectors: the five tools appear.
   For a Genie Agent: Configure → Resources → Connectors → Add.

The secret expires: before then, generate a new one and update the connection.

## 3. Test

Ask Genie *"Does Programme A help patients?"*. It should call `describe_data`
and `review_study`, ask about outcome, follow-up, covariates and population,
show a summary to confirm, and only then call `run_study`.

Reference result on the synthetic data (ED attendance count, 12 months,
matched on age, gender and prior ED use, everyone): **rate ratio 0.97
(95% CI 0.65–1.46), p = 0.90**, 135 treated vs 135 matched controls.

## 4. Moving to another workspace (Healix)

Every line to change is marked `HEALIX` (search for it):

| File | What to change |
| --- | --- |
| `backend/app.yaml` | `CORS_ORIGINS`: the new workspace URL |
| `backend/config/mapping.yaml` | The `workspace.cohort.` prefix on the four tables; with real data, also the marked column names and coverage dates |
| `backend/requirements.txt` | If packages come from an internal mirror: its `--index-url` as the first line (in that workspace's copy only, never committed) |
| `notebooks/load_synthetic_data.py` | The catalog and schema widgets (synthetic data only) |

Then redo sections 1–3 in the new workspace. Check first that its Apps can
install the 12 packages in `requirements.txt`.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Deploy fails installing packages | The workspace can't reach PyPI, or its mirror blocks a package: add the mirror's `--index-url` (section 4) and check each package is allowed |
| HTTP 503 "App Not Available" | The app is stopped (Free Edition stops idle apps): Start it |
| HTTP 401 from Unity Gateway | The caller service principal lacks **Can Use** on the app |
| Genie Code can't connect (CORS) | `CORS_ORIGINS` is not the exact workspace URL |
| "Failed to generate OAuth token" | The platform's sign-in between agent and app: retry, or reconnect the connector |
| "No Databricks credentials" | Not running as an App, or the app has no service principal yet |
| "DATABRICKS_WAREHOUSE_ID is not set" | No SQL warehouse resource, or its key is not `sql-warehouse` (section 1 step 3) |
| "SQL warehouse could not run the query" | Missing grants (step 4), tables not loaded (step 2), or `mapping.yaml` names don't match the tables |
