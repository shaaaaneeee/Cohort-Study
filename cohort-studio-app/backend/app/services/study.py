"""The study builder's operations: check, attrition, preview, analysis and the assistant.

Routes stay thin and call these. Each method returns a plain dict ready to
be sent as JSON (NaN and infinity already replaced by None).
"""

from typing import Any

from app.ai.llm.base import LLMClient
from app.analysis.outcome_models import implied_model
from app.analysis.runner import run_analysis
from app.analysis.validation import check_small_cells, validate_study
from app.core.jsonsafe import clean
from app.db.repositories.cohort import CohortRepository
from app.schemas.study import FeatureSpec, StudySpec
from app.services import assistant
from app.services.catalogue import catalogue


class StudyService:
    def __init__(self, repository: CohortRepository):
        self.repository = repository
        self.mapping = repository.mapping

    def metadata(self) -> dict[str, Any]:
        return catalogue(self.mapping)

    def dimension_values(self, source: str, dimension: str) -> list[str]:
        """Raises LookupError for a source or dimension that is not in the mapping."""
        return self.repository.dimension_values(source, dimension)

    def check(self, spec: StudySpec) -> dict[str, Any]:
        """Every design issue, and the model the outcome implies, without building the cohort.

        Cheap enough to call on every change in the study builder, so the
        user sees problems and the model choice before running anything.
        """
        outcomes = [f for f in spec.features if f.role == "outcome"]
        model = implied_model(outcomes[0]) if len(outcomes) == 1 else None
        return {
            "issues": validate_study(spec, self.mapping, self.repository.dimension_values),
            "model": model,
        }

    def attrition(self, spec: StudySpec) -> dict[str, Any]:
        """Patients left after each eligibility step, by group."""
        steps = self.repository.attrition_counts(spec)
        cells = {}
        for step in steps:
            cells[f"{step['step']} (treated)"] = step["treated"]
            cells[f"{step['step']} (controls)"] = step["control"]
        return {"steps": steps, "issues": self._warnings(spec) + check_small_cells(cells)}

    def preview(self, feature: FeatureSpec, study: StudySpec) -> dict[str, Any]:
        """One feature's values in the study's cohort, by group."""
        summary = self.repository.feature_preview(feature, study)
        others = [f for f in study.features if f.name != feature.name]
        combined = study.model_copy(update={"features": [*others, feature]})
        design = [i for i in self._warnings(combined) if i["feature"] == feature.name]
        summary["issues"] = design + summary["issues"]
        return clean(summary)  # type: ignore[return-value]

    def analysis(self, spec: StudySpec) -> dict[str, Any]:
        """Build the analysis table and run the statistics. See analysis.runner.run_analysis."""
        result = run_analysis(self.repository.analysis_table(spec), spec)
        result["issues"] = self._warnings(spec) + result["issues"]
        return clean(result)  # type: ignore[return-value]

    def chat(
        self, history: list[dict[str, Any]], draft: StudySpec | None, client: LLMClient
    ) -> dict[str, Any]:
        """One turn with the study assistant. See services.assistant.converse.

        The assistant only drafts the study. Running it is left to analysis(),
        after the user has reviewed the draft in the builder.
        """
        result = assistant.converse(
            history,
            draft,
            catalogue(self.mapping),
            self.mapping,
            self.repository.dimension_values,
            client,
        )
        return clean(result)  # type: ignore[return-value]

    def _warnings(self, spec: StudySpec) -> list[dict[str, Any]]:
        """The design warnings for a study. Errors are raised by the repository instead."""
        issues = validate_study(spec, self.mapping, self.repository.dimension_values)
        return [i for i in issues if i["level"] == "warning"]
