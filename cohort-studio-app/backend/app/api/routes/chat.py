from fastapi import APIRouter

from app.api.deps import LLMClientDep, StudyServiceDep
from app.schemas.api import ChatRequest, ChatResult, ErrorBody

router = APIRouter(tags=["assistant"])


@router.post(
    "/chat",
    response_model=ChatResult,
    responses={422: {"model": ErrorBody}, 503: {"model": ErrorBody}},
)
def chat(request: ChatRequest, service: StudyServiceDep, client: LLMClientDep) -> dict:
    """One turn with the study assistant.

    Returns the reply, any questions, and the drafted study with its issues.
    The assistant only drafts; running the study is left to /api/analysis.
    """
    history = [m.model_dump() for m in request.messages]
    return service.chat(history, request.draft, client)
