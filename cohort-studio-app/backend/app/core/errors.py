"""Every error response has the same shape, so the UI can show any failure the same way.

    {"message": "...", "issues": [{"level", "code", "message", "feature"}, ...]}

with issues in the format analysis.validation.issue() makes:
    401  a missing or wrong X-API-Key, when API_KEY is set
    404  an unknown path, or a source or dimension that is not in the mapping
    422  a request that is not a valid study, a study with design errors,
         or data that cannot support the analysis
    503  the database or the study assistant's language model could not be reached
    500  anything else; the details go to the log, not to the client
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.llm.base import LLMError
from app.analysis.validation import issue, issues_from_pydantic
from app.core.exceptions import AnalysisError, DataSourceError, StudyError

log = logging.getLogger(__name__)


def error_response(status: int, message: str, issues: list[dict] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"message": message, "issues": issues or []})


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StudyError)
    async def study_error(request: Request, e: StudyError) -> JSONResponse:
        return error_response(422, "The study has design errors.", e.issues)

    @app.exception_handler(AnalysisError)
    async def analysis_error(request: Request, e: AnalysisError) -> JSONResponse:
        return error_response(422, str(e), [issue("error", "analysis_failed", str(e))])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, e: RequestValidationError) -> JSONResponse:
        return error_response(
            422, "The request is not a valid study.", issues_from_pydantic(list(e.errors()))
        )

    @app.exception_handler(LLMError)
    async def llm_error(request: Request, e: LLMError) -> JSONResponse:
        log.warning("assistant unavailable: %s", e)
        return error_response(503, str(e), [issue("error", "assistant_unavailable", str(e))])

    @app.exception_handler(DataSourceError)
    async def data_source_error(request: Request, e: DataSourceError) -> JSONResponse:
        return error_response(503, str(e), [issue("error", "database_unavailable", str(e))])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, e: StarletteHTTPException) -> JSONResponse:
        response = error_response(e.status_code, str(e.detail))
        if e.headers:
            response.headers.update(e.headers)
        return response

    @app.exception_handler(Exception)
    async def unexpected(request: Request, e: Exception) -> JSONResponse:
        log.error("unhandled error", exc_info=e)
        return error_response(500, "Something went wrong on the server.")
