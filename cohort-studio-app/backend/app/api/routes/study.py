from fastapi import APIRouter

from app.api.deps import StudyServiceDep
from app.schemas.api import (
    AnalysisResult,
    AttritionResult,
    CheckResult,
    ErrorBody,
    PreviewRequest,
    PreviewResult,
)
from app.schemas.study import StudySpec

router = APIRouter(tags=["study"], responses={422: {"model": ErrorBody}})


@router.post("/study/check", response_model=CheckResult)
def check(spec: StudySpec, service: StudyServiceDep) -> dict:
    """Every design issue, and the model the outcome implies, without building the cohort."""
    return service.check(spec)


@router.post("/attrition", response_model=AttritionResult)
def attrition(spec: StudySpec, service: StudyServiceDep) -> dict:
    """Patients left after each eligibility step, by group."""
    return service.attrition(spec)


@router.post("/preview", response_model=PreviewResult)
def preview(request: PreviewRequest, service: StudyServiceDep) -> dict:
    """One feature's values in the study's cohort, by group."""
    return service.preview(request.feature, request.study)


@router.post("/analysis", response_model=AnalysisResult)
def analysis(spec: StudySpec, service: StudyServiceDep) -> dict:
    """Matching, balance, the effect estimate and every warning."""
    return service.analysis(spec)
