"""The FastAPI app.

    python -m app                                   # serves on HOST:PORT from the environment
    uvicorn app.main:create_app --factory           # the same, through uvicorn directly

create_app() builds the app around a repository. In production it makes one
on PostgreSQL from the settings; tests pass their own.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from app import __version__
from app.ai.llm.base import LLMClient
from app.api.deps import require_api_key
from app.api.routes import chat, health, metadata, study
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logs import configure_logging, request_logging
from app.core.mapping import load_mapping
from app.db.dialect import PostgresDialect
from app.db.repositories.cohort import CohortRepository, SqlCohortRepository
from app.db.session import create_db_engine, ping, query_runner
from app.services.study import StudyService

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    repository: CohortRepository | None = None,
    llm_client: LLMClient | None = None,
    db_check: Callable[[], None] | None = None,
) -> FastAPI:
    """The app. llm_client is made from the settings on the first chat if not given."""
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    engine: Engine | None = None
    if repository is None:
        mapping = load_mapping(settings.mapping_path)
        engine = create_db_engine(settings)
        repository = SqlCohortRepository(mapping, PostgresDialect(), query_runner(engine))
        if db_check is None:

            def db_check() -> None:
                ping(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info(
            "starting",
            extra={
                "version": __version__,
                "env": settings.app_env,
                "llm_provider": settings.resolved_llm_provider,
            },
        )
        yield
        if engine is not None:
            engine.dispose()

    app = FastAPI(
        title="Cohort Studio API",
        version=__version__,
        lifespan=lifespan,
        # The interactive docs are useful locally and in staging, and
        # reveal nothing the frontend does not already show.
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.study_service = StudyService(repository)
    app.state.llm_client = llm_client
    app.state.db_check = db_check or (lambda: None)

    register_error_handlers(app)
    app.middleware("http")(request_logging)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
            expose_headers=["X-Request-ID"],
            max_age=600,
        )

    api = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)])
    api.include_router(metadata.router)
    api.include_router(study.router)
    api.include_router(chat.router)
    app.include_router(api)
    app.include_router(health.router)
    return app
