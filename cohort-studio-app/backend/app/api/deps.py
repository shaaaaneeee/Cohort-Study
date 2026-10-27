"""Dependencies the routes share: the study service, the model client and the API key check."""

import secrets
import threading
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.ai.llm.base import LLMClient
from app.ai.llm.factory import client_from_settings
from app.core.config import Settings
from app.services.study import StudyService

_llm_lock = threading.Lock()


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_study_service(request: Request) -> StudyService:
    service: StudyService = request.app.state.study_service
    return service


def get_llm_client(request: Request) -> LLMClient:
    """The model client, made from the settings on the first chat if none was given."""
    state = request.app.state
    if state.llm_client is None:
        with _llm_lock:
            if state.llm_client is None:
                state.llm_client = client_from_settings(state.settings)
    client: LLMClient = state.llm_client
    return client


def require_api_key(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    """When API_KEY is set, every /api request must send it in X-API-Key."""
    if settings.api_key is None:
        return
    sent = request.headers.get("x-api-key", "")
    if not secrets.compare_digest(sent.encode(), settings.api_key.get_secret_value().encode()):
        raise HTTPException(
            status_code=401,
            detail="A valid X-API-Key header is required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


StudyServiceDep = Annotated[StudyService, Depends(get_study_service)]
LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]
