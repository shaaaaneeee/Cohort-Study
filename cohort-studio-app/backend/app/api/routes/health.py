import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.schemas.api import Health

router = APIRouter(tags=["health"])
log = logging.getLogger(__name__)


@router.get("/health", response_model=Health, responses={503: {"model": Health}})
def health(request: Request) -> JSONResponse:
    """200 when the API is up and the database answers, 503 otherwise.

    Used by the container HEALTHCHECK and Northflank's health checks. Never
    needs the API key.
    """
    try:
        request.app.state.db_check()
        database = "ok"
    except Exception:
        log.warning("health check: database unavailable", exc_info=True)
        database = "unavailable"
    status = "ok" if database == "ok" else "unavailable"
    return JSONResponse(
        status_code=200 if status == "ok" else 503,
        content={"status": status, "database": database, "version": __version__},
    )
