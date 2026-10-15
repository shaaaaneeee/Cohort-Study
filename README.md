# Northflank sandbox (Phase 0, M0.5)

A minimal frontend + FastAPI backend + PostgreSQL deployment, built to learn
Northflank before the real Cohort Study application. It is a throwaway
learning project, not the application.

```
browser ──▶ frontend (nginx, static HTML) ──calls──▶ backend (FastAPI) ──▶ PostgreSQL
                                                         ▲
                                       secrets: DATABASE_URL, DEMO_SECRET
```

| Path | What it is |
|---|---|
| `backend/app/main.py` | FastAPI app: health, database check, notes table, secret check, test error, JSON logs with a request ID |
| `backend/Dockerfile` | Python 3.12 image, runs as a non-root user on port 8000 |
| `frontend/index.html` | One page with a button for each check |
| `frontend/Dockerfile`, `write-config.sh` | nginx image; writes `config.js` from `BACKEND_URL` at start-up |

## Before you start

1. Push this folder to a Git repository of your own (GitHub, GitLab or Bitbucket).
2. In Northflank, connect that Git account (account or team settings → Git integrations).

Northflank's screens change over time. If a button below is named slightly
differently, look for the closest match, and note the real name in the
"What I found" section at the end.

## Step 1. Create a project

Create a new **project**, for example `cohort-sandbox`, in a region close to you.
A project holds every service, database and secret for one application.

## Step 2. Add PostgreSQL

1. In the project, create an **addon** and choose **PostgreSQL**.
2. Pick the smallest plan. It provisions in a few minutes.
3. Open the addon's **connection details**. Find the connection string
   (`postgresql://user:password@host:port/db`). Use the **internal**
   one: the backend reaches the database inside the project's private network.

## Step 3. Create a secret group

1. Create a **secret group**, for example `backend-secrets`.
2. Add these variables:
   - `DATABASE_URL`: link it to the PostgreSQL addon's connection string. Northflank
     can link addon connection details into a secret group, so the
     password is never copied by hand. If linking gives the variable a different
     name, rename or alias it to `DATABASE_URL`.
   - `DEMO_SECRET`: any value you make up.
   - `LOG_LEVEL`: `INFO`.
3. Restrict the group to the backend service only. Secrets should reach only the
   services that need them.

## Step 4. Deploy the backend

1. Create a **combined service** (build and deploy in one), named `backend`.
2. Repository: your repo. Branch: `main`.
3. Build type: **Dockerfile**. Build context `/backend`, Dockerfile `/backend/Dockerfile`.
4. Port: **8000**, protocol HTTP, **public** (so the browser can call it).
5. Create it and watch the **build logs**. The `pip install` step shows how
   dependencies are installed from `requirements.txt` during the build.
6. When it is running, open `https://<backend URL>/health`. You should see `{"status":"ok"}`.
   `https://<backend URL>/docs` shows every endpoint.

## Step 5. Deploy the frontend

1. Create another combined service, `frontend`, from the same repo.
2. Build context `/frontend`, Dockerfile `/frontend/Dockerfile`. Port **80**, public.
3. Add the environment variable `BACKEND_URL` = the backend's public URL (no slash at the end).
   This is configuration, not a secret, so it can be a plain variable.
4. Back on the backend, add `FRONTEND_ORIGIN` = the frontend's public URL, so the
   browser is allowed to call the backend (CORS). Restart the backend.

## Step 6. Check everything from the frontend

Open the frontend URL and press each button:

| Button | Expected | Proves |
|---|---|---|
| Backend health | `200 {"status":"ok"}` | The services are deployed and reachable |
| Database connection | `200` and the PostgreSQL version | Backend to database connectivity |
| Save, then List notes | Your note comes back | Reads and writes to the database |
| Secret | `present: true`, a length and a hash prefix | The secret is readable but never exposed |
| Test error | `500` and a request ID | Ready for the logs step |

If a button says `Request failed`, it is usually CORS: check `FRONTEND_ORIGIN`
exactly matches the frontend URL, including `https://`.

## Step 7. Trace the test error through the logs

1. Press **Test error** and copy the request ID it shows.
2. Open the backend service's **runtime logs** and search for that ID.
3. You will find two JSON lines with the same `request_id`: an `ERROR` with the full
   traceback (`RuntimeError: Test error raised on purpose`), and the request
   line with `"status": 500`.
4. Compare with the **build logs** (the image build) and the **deployment** events
   (container started, restarted). Knowing which log holds what is most of troubleshooting.

Also try breaking it on purpose: change `DATABASE_URL` to a wrong password, restart,
press Database connection, and find `database connection failed` in the logs.
Then fix it.

## Run the backend on your own computer

```
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

Database endpoints answer 503 until `DATABASE_URL` is set.

## What I found (fill in as you go)

- Where build logs, runtime logs and deployment events live:
- How the addon's connection string reached the backend:
- How secrets are restricted to one service:
- Anything that went wrong and how I fixed it:
- GovPaaS: how its workflow and deployment model differ from this:
