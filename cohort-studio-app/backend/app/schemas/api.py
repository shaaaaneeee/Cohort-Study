"""Request and response bodies of the HTTP API.

The study itself (StudySpec, FeatureSpec) is in schemas/study.py. The
frontend's TypeScript types are generated from the OpenAPI document these
models produce (see scripts/export_openapi.py), so a change here shows up as
a type error in the frontend rather than at run time.

Response models allow extra fields: they describe what the endpoints return
without silently dropping anything the analysis adds later.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.study import FeatureSpec, StudySpec


class Response(BaseModel):
    model_config = ConfigDict(extra="allow")


# ------------------------------------------------------------------ requests


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: FeatureSpec
    study: StudySpec


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatRequest(BaseModel):
    """One turn: the visible conversation, ending with the user, and the current study.

    draft is the study in the builder, including any changes the user made by
    hand, so the assistant refines what the user sees rather than its own
    last proposal.
    """

    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    draft: StudySpec | None = None

    @model_validator(mode="after")
    def _ends_with_user(self) -> "ChatRequest":
        if self.messages[0].role != "user" or self.messages[-1].role != "user":
            raise ValueError("the conversation must start and end with a user message")
        return self


# ----------------------------------------------------------------- responses


class Issue(Response):
    level: Literal["error", "warning"]
    code: str
    message: str
    feature: str | None = None


class ErrorBody(Response):
    message: str
    issues: list[Issue]


class Named(Response):
    name: str
    label: str


class MeasureInfo(Named):
    aggregations: list[str]


class Coverage(Response):
    start: date | None = None
    end: date | None = None


class SourceInfo(Named):
    granularity: Literal["day", "month", "year"]
    coverage: Coverage
    dimensions: list[Named]
    measures: list[MeasureInfo]


class AggregationInfo(Response):
    name: str
    description: str


class Metadata(Response):
    dataset: str
    exposures: list[Named]
    person_attributes: list[str]
    person_covariates: list[str]
    sources: list[SourceInfo]
    aggregations: list[AggregationInfo]
    roles: list[str]
    window_units: list[str]
    period_grains: list[str]


class ImpliedModel(Response):
    model: str
    measure: str
    name: str
    reason: str


class CheckResult(Response):
    issues: list[Issue]
    model: ImpliedModel | None


class AttritionStep(Response):
    step: str
    treated: int
    control: int


class AttritionResult(Response):
    steps: list[AttritionStep]
    issues: list[Issue]


class GroupStats(Response):
    n: int
    nonzero: int
    mean: float | None
    min: float | None
    max: float | None


class PreviewColumn(Response):
    column: str
    treated: GroupStats
    control: GroupStats


class PreviewResult(Response):
    feature: str
    columns: list[PreviewColumn]
    issues: list[Issue]


class FittedModel(ImpliedModel):
    estimate: float | None
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    parameters: int
    dispersion: float | None = None
    ph_p_value: float | None = None


class CohortSizes(Response):
    treated: int
    control: int
    treated_matched: int
    control_matched: int
    matched: bool


class GroupCounts(Response):
    treated: int
    control: int


class BalanceRow(Response):
    covariate: str
    treated_mean_before: float | None
    control_mean_before: float | None
    smd_before: float | None
    treated_mean_after: float | None
    control_mean_after: float | None
    smd_after: float | None


class GroupSeries(Response):
    treated: list[float | None]
    control: list[float | None]


class PropensityPlot(Response):
    edges: list[float]
    before: GroupSeries
    after: GroupSeries


class SurvivalPlot(GroupSeries):
    days: list[float]


class PeriodsPlot(GroupSeries):
    periods: list[str]


class Plots(Response):
    propensity: PropensityPlot | None
    survival: SurvivalPlot | None
    periods: PeriodsPlot | None


class AnalysisResult(Response):
    model: FittedModel
    cohort: CohortSizes
    events: GroupCounts
    balance: list[BalanceRow]
    issues: list[Issue]
    interpretation: str
    plots: Plots


class ChatResult(Response):
    status: Literal["ready", "asking", "unsupported"]
    reply: str
    questions: list[str]
    draft: StudySpec | None
    issues: list[Issue]
    model: ImpliedModel | None


class Health(Response):
    status: Literal["ok", "unavailable"]
    database: Literal["ok", "unavailable"]
    version: str
