# Cohort Study

The Cohort Studio MCP server: tools that let AI agents (Genie One, Genie
Code, the Databricks AI Playground) design and run observational cohort
studies with a fixed, tested method, asking the user before they assume.

- The server and how it works: [`cohort-studio-app/`](cohort-studio-app/README.md)
- Loading the data, deploying on Databricks and connecting agents: [`cohort-studio-app/docs/databricks-app.md`](cohort-studio-app/docs/databricks-app.md)

`main` holds only what runs on Databricks: the MCP server, the Databricks
query path, and the synthetic data generator with a notebook that loads it.
Earlier versions are kept on branches: `archive/web-app-and-assistant` (the
web app and its study assistant) and `archive/mcp-with-postgres-tests`
(PostgreSQL support and the test suite).
