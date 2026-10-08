"""HTTP API for the study builder, and the builder's pages at /.

    python -m cohort_studio.api          # http://127.0.0.1:8765, or set PORT

The config file is config/mapping.yaml unless COHORT_CONFIG names another.
create_app() builds the app around a repository, so tests can pass one on a
test database.

Every error response has the same shape, {"message": ..., "issues": [...]},
with issues in the format validator.issue() makes, so the UI can show any
failure the same way:
    404  a source or dimension that is not in the mapping (value lookups)
    422  a request that is not a valid study, a study with design errors,
         or data that cannot support the analysis
"""
import math
import os
from pathlib import Path
from typing import get_args

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from cohort_studio.analysis import run_analysis
from cohort_studio.features import AGGREGATIONS, FeatureSpec, Periodise, StudySpec, Window
from cohort_studio.mapping import Mapping, load_mapping
from cohort_studio.models import AnalysisError, implied_model
from cohort_studio.repository import CohortRepository, StudyError, open_repository
from cohort_studio.validator import check_small_cells, issue, validate_study

DEFAULT_CONFIG = Path(__file__).parent.parent / "config" / "mapping.yaml"
WEB_DIR = Path(__file__).parent.parent / "web"


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: FeatureSpec
    study: StudySpec


def create_app(repository: CohortRepository, mapping: Mapping) -> FastAPI:
    app = FastAPI(title="cohort-studio")

    def warnings_for(spec: StudySpec) -> list[dict]:
        """The design warnings for a study. Errors are raised by the repository instead."""
        found = []
        for i in validate_study(spec, mapping, repository.dimension_values):
            if i["level"] == "warning":
                found.append(i)
        return found

    # ---------------------------------------------------------------- errors

    @app.exception_handler(StudyError)
    def study_error(request: Request, e: StudyError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "message": "The study has design errors.", "issues": e.issues})

    @app.exception_handler(AnalysisError)
    def analysis_error(request: Request, e: AnalysisError) -> JSONResponse:
        return JSONResponse(status_code=422, content={
            "message": str(e), "issues": [issue("error", "analysis_failed", str(e))]})

    @app.exception_handler(RequestValidationError)
    def invalid_request(request: Request, e: RequestValidationError) -> JSONResponse:
        # pydantic's errors, reworded into the issue format. loc is the path
        # to the bad field, such as body > features > 0 > window > from.
        issues = []
        for error in e.errors():
            where = []
            for part in error["loc"]:
                if part != "body":
                    where.append(str(part))
            issues.append(issue("error", "invalid_request", f"{' > '.join(where)}: {error['msg']}"))
        return JSONResponse(status_code=422, content={
            "message": "The request is not a valid study.", "issues": issues})

    # ------------------------------------------------------------- endpoints

    @app.get("/api/metadata")
    def metadata() -> dict:
        """Everything the study builder can offer, from the mapping config.

        Physical table and column names other than dimensions and measures
        are left out: the UI has no use for them.
        """
        sources = []
        for name, source in mapping.feature_sources().items():
            dimensions = []
            for column, dimension in source.dimensions.items():
                dimensions.append({"name": column, "label": dimension.label})
            measures = []
            for column, measure in source.measures.items():
                measures.append({"name": column, "label": measure.label, "aggregations": measure.agg})
            sources.append({"name": name, "label": source.label or name,
                            "granularity": source.granularity,
                            "coverage": {"start": source.coverage.start, "end": source.coverage.end},
                            "dimensions": dimensions, "measures": measures})
        exposures = []
        for x in mapping.exposure:
            exposures.append({"name": x.name, "label": x.label or x.name})
        aggregations = []
        for name, description in AGGREGATIONS.items():
            aggregations.append({"name": name, "description": description})
        return {
            "dataset": mapping.dataset,
            "exposures": exposures,
            "person_attributes": mapping.person.attributes,
            "person_covariates": ["age"] + mapping.person.attributes,
            "sources": sources,
            "aggregations": aggregations,
            "roles": list(get_args(FeatureSpec.model_fields["role"].annotation)),
            "window_units": list(get_args(Window.model_fields["unit"].annotation)),
            "period_grains": list(get_args(Periodise.model_fields["grain"].annotation)),
        }

    @app.get("/api/values/{source}/{dimension}", response_model=list[str])
    def dimension_values(source: str, dimension: str):
        """The values a dimension takes. Use source "person" for person attributes."""
        # Handled here rather than app-wide: KeyError is a kind of
        # LookupError, and a bug raising one anywhere else should not
        # come back looking like a 404.
        try:
            return repository.dimension_values(source, dimension)
        except LookupError as e:
            return JSONResponse(status_code=404, content={"message": str(e), "issues": []})

    @app.post("/api/study/check")
    def check(spec: StudySpec) -> dict:
        """Every design issue, and the model the outcome implies, without building the cohort.

        Cheap enough to call on every change in the study builder, so the
        user sees problems and the model choice before running anything.
        """
        outcomes = []
        for f in spec.features:
            if f.role == "outcome":
                outcomes.append(f)
        model = None
        if len(outcomes) == 1:
            model = implied_model(outcomes[0])
        return {"issues": validate_study(spec, mapping, repository.dimension_values),
                "model": model}

    @app.post("/api/attrition")
    def attrition(spec: StudySpec) -> dict:
        """Patients left after each eligibility step, by group."""
        steps = repository.attrition_counts(spec)
        cells = {}
        for step in steps:
            cells[f"{step['step']} (treated)"] = step["treated"]
            cells[f"{step['step']} (controls)"] = step["control"]
        return {"steps": steps, "issues": warnings_for(spec) + check_small_cells(cells)}

    @app.post("/api/preview")
    def preview(request: PreviewRequest) -> dict:
        """One feature's values in the study's cohort, by group."""
        summary = repository.feature_preview(request.feature, request.study)
        others = []
        for f in request.study.features:
            if f.name != request.feature.name:
                others.append(f)
        combined = request.study.model_copy(update={"features": others + [request.feature]})
        design = []
        for i in warnings_for(combined):
            if i["feature"] == request.feature.name:
                design.append(i)
        summary["issues"] = design + summary["issues"]
        return clean(summary)

    @app.post("/api/analysis")
    def analysis(spec: StudySpec) -> dict:
        """Build the analysis table and run the statistics. See analysis.run_analysis."""
        result = run_analysis(repository.analysis_table(spec), spec)
        result["issues"] = warnings_for(spec) + result["issues"]
        return clean(result)

    # The study builder's pages, at /. Mounted last so the /api routes
    # above are matched first.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


def clean(value):
    """Replace NaN and infinity, which JSON cannot carry, with None, all the way down."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            result[key] = clean(item)
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.append(clean(item))
        return result
    return value


def main() -> None:
    mapping = load_mapping(os.environ.get("COHORT_CONFIG", DEFAULT_CONFIG))
    app = create_app(open_repository(mapping), mapping)
    # Only this computer can connect. There is no authentication yet, so the
    # app must not be reachable from the network.
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8765")))


if __name__ == "__main__":
    main()
