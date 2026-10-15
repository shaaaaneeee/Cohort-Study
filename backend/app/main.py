"""Sandbox backend for learning Northflank (Phase 0, M0.5).

Shows the four things the deployment has to prove:
    - the backend runs and answers           GET  /health
    - it reaches PostgreSQL                  GET  /api/db, GET/POST /api/notes
    - it reads a secret without exposing it  GET  /api/secret-check
    - errors can be traced through the logs  GET  /api/error

Configuration comes only from environment variables, which Northflank fills
from a secret group:
    DATABASE_URL     postgresql://user:password@host:port/dbname
    DEMO_SECRET      any value; only a fingerprint of it is ever shown
    FRONTEND_ORIGIN  the frontend's public URL, allowed by CORS (default *)
    LOG_LEVEL        INFO by default
"""
import hashlib
import json
import logging
import os
import sys
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


# ------------------------------------------------------------ logging

class JsonFormatter(logging.Formatter):
    """One JSON object per line, so the platform's log viewer can search fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def setup_logging() -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
    return logging.getLogger("sandbox")


log = setup_logging()


def info(message: str, **fields) -> None:
    log.info(message, extra={"fields": fields})


# ------------------------------------------------------------ app

app = FastAPI(title="Northflank sandbox backend")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "*")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_log(request: Request, call_next):
    """Log every request with an id, also returned as a header, to find it in the logs."""
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error", extra={"fields": {
            "request_id": request_id, "path": request.url.path, "method": request.method}})
        response = JSONResponse(status_code=500, content={
            "error": "Internal error", "request_id": request_id})
    info("request", request_id=request_id, method=request.method, path=request.url.path,
         status=response.status_code, ms=round((time.perf_counter() - start) * 1000, 1))
    response.headers["X-Request-ID"] = request_id
    return response


# ------------------------------------------------------------ database

def connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(503, "DATABASE_URL is not set. Link the database's secret to this service.")
    import psycopg  # imported here so /health works even without the driver
    try:
        return psycopg.connect(url, connect_timeout=5)
    except psycopg.OperationalError as e:
        log.error("database connection failed", extra={"fields": {"reason": str(e).splitlines()[0]}})
        raise HTTPException(503, "Could not connect to the database. See the backend logs.") from None


class Note(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/db")
def db_check() -> dict:
    with connect() as conn:
        version = conn.execute("SELECT version()").fetchone()[0]
    return {"connected": True, "server": version.split(",")[0]}


@app.post("/api/notes")
def add_note(note: Note) -> dict:
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS notes ("
                     "id SERIAL PRIMARY KEY, text TEXT NOT NULL, created TIMESTAMPTZ DEFAULT now())")
        row = conn.execute("INSERT INTO notes (text) VALUES (%s) RETURNING id", (note.text,)).fetchone()
    info("note added", note_id=row[0])
    return {"id": row[0]}


@app.get("/api/notes")
def list_notes() -> list[dict]:
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS notes ("
                     "id SERIAL PRIMARY KEY, text TEXT NOT NULL, created TIMESTAMPTZ DEFAULT now())")
        rows = conn.execute("SELECT id, text, created FROM notes ORDER BY id DESC LIMIT 20").fetchall()
    return [{"id": r[0], "text": r[1], "created": r[2].isoformat()} for r in rows]


# ------------------------------------------------------------ secrets and errors

@app.get("/api/secret-check")
def secret_check() -> dict:
    """Prove the secret is readable without revealing it: a short hash, never the value."""
    value = os.environ.get("DEMO_SECRET")
    if value is None:
        return {"present": False}
    fingerprint = hashlib.sha256(value.encode()).hexdigest()[:8]
    return {"present": True, "length": len(value), "sha256_prefix": fingerprint}


@app.get("/api/error")
def test_error():
    """Fails on purpose, to practise tracing a failed request through the logs."""
    raise RuntimeError("Test error raised on purpose from /api/error")
