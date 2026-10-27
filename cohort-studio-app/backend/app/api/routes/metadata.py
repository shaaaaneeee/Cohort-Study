from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api.deps import StudyServiceDep
from app.core.errors import error_response
from app.schemas.api import ErrorBody, Metadata

router = APIRouter(tags=["metadata"])


@router.get("/metadata", response_model=Metadata)
def metadata(service: StudyServiceDep) -> dict:
    """Everything the study builder can offer, from the mapping config."""
    return service.metadata()


@router.get(
    "/values/{source}/{dimension}", response_model=list[str], responses={404: {"model": ErrorBody}}
)
def dimension_values(
    source: str, dimension: str, service: StudyServiceDep
) -> list[str] | JSONResponse:
    """The values a dimension takes. Use source "person" for person attributes."""
    # Handled here rather than app-wide: KeyError is a kind of LookupError,
    # and a bug raising one anywhere else should not come back as a 404.
    try:
        return service.dimension_values(source, dimension)
    except LookupError as e:
        return error_response(404, str(e))
