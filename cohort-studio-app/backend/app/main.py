"""The MCP server app.

    python -m app                                   # serves on HOST:PORT (DATABRICKS_APP_PORT)
    uvicorn app.main:create_app --factory           # the same, through uvicorn directly

Serves the study tools to AI agents (Genie One, Genie Code, the AI Playground)
over MCP at /mcp, plus /health. create_app() builds the study service on the
Databricks SQL warehouse and the tables the mapping names. A caller can pass
its own repository instead, e.g. to try the tools on in-memory data.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.core.config import Settings, get_settings
from app.core.logs import configure_logging, request_logging
from app.core.mapping import load_mapping
from app.db.databricks import databricks_ping, databricks_runner
from app.db.dialect import dialect_for
from app.db.repositories.cohort import CohortRepository, SqlCohortRepository
from app.mcp_server import TrailingSlash, build_mcp, mcp_asgi_app
from app.services.study import StudyService

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    repository: CohortRepository | None = None,
    db_check: Callable[[], None] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    if repository is None:
        mapping = load_mapping(settings.mapping_path)
        run = databricks_runner(settings)
        db_check = db_check or databricks_ping(run)
        repository = SqlCohortRepository(mapping, dialect_for(mapping.backend.dialect), run)

    mcp = build_mcp(StudyService(repository))
    token = settings.mcp_token.get_secret_value() if settings.mcp_token else None
    check_database = db_check or (lambda: None)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("starting", extra={"version": __version__, "env": settings.app_env})
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="Cohort Studio MCP server",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    @app.get("/health")
    def health() -> JSONResponse:
        """200 when the server is up and the database answers, 503 otherwise."""
        try:
            check_database()
            database = "ok"
        except Exception:
            log.warning("health check: database unavailable", exc_info=True)
            database = "unavailable"
        return JSONResponse(
            status_code=200 if database == "ok" else 503,
            content={"status": database, "database": database, "version": __version__},
        )

    app.middleware("http")(request_logging)
    if settings.cors_origins:
        # Genie Code calls /mcp from the workspace page in the browser, with
        # the workspace's sign-in, so the workspace must be an allowed origin.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "Content-Type",
                "Accept",
                "Authorization",
                "X-Request-ID",
                "Mcp-Session-Id",
                "Mcp-Protocol-Version",
                "Last-Event-ID",
            ],
            allow_credentials=True,
            expose_headers=["X-Request-ID", "Mcp-Session-Id"],
            max_age=600,
        )
    app.mount("/mcp", mcp_asgi_app(mcp, token))
    app.add_middleware(TrailingSlash)
    return app
