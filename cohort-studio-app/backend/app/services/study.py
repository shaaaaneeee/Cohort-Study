"""The study builder's operations: check, attrition, preview, analysis and the assistant.

Routes stay thin and call these. Each method returns a plain dict ready to
be sent as JSON (NaN and infinity already replaced by None).
"""

import logging
from typing import Any

import numpy as np

from app.ai.llm.base import LLMClient
from app.analysis.outcome_models import implied_model
from app.analysis.runner import run_analysis
from app.analysis.validation import check_cohort_size, check_small_cells, issue, validate_study
from app.core.exceptions import AnalysisError, DataSourceError, StudyError
from app.core.jsonsafe import clean
from app.db.repositories.cohort import CohortRepository
from app.schemas.study import FeatureSpec, StudySpec
from app.services import assistant
from app.services.catalogue import catalogue

log = logging.getLogger(__name__)


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
        issues = validate_study(spec, self.mapping, self.repository.dimension_values)
        if not any(i["level"] == "error" for i in issues):
            issues += self.size_issues(spec)
        return {"issues": issues, "model": model}

    def group_sizes(self, spec: StudySpec) -> tuple[int, int] | None:
        """Treated and control patients left after every eligibility step.

        None when the counts cannot be worked out (for example, the study
        still has design errors, or the database is unreachable); the size
        check is then skipped rather than blocking the user.
        """
        try:
            steps = self.repository.attrition_counts(spec)
        except Exception:
            log.warning("could not count the cohort", exc_info=True)
            return None
        if not steps:
            return None
        return steps[-1]["treated"], steps[-1]["control"]

    def size_issues(self, spec: StudySpec) -> list[dict[str, Any]]:
        sizes = self.group_sizes(spec)
        return check_cohort_size(*sizes) if sizes else []

    def attrition(self, spec: StudySpec) -> dict[str, Any]:
        """Patients left after each eligibility step, by group."""
        steps = self.repository.attrition_counts(spec)
        cells = {}
        for step in steps:
            cells[f"{step['step']} (treated)"] = step["treated"]
            cells[f"{step['step']} (controls)"] = step["control"]
        size = check_cohort_size(steps[-1]["treated"], steps[-1]["control"]) if steps else []
        return {
            "steps": steps,
            "issues": size + self._warnings(spec) + check_small_cells(cells),
        }

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
        table = self.repository.analysis_table(spec)
        try:
            result = run_analysis(table, spec)
        except (ArithmeticError, ValueError, np.linalg.LinAlgError) as e:
            # A numerical failure the runner did not foresee: report it as a
            # study the data cannot support, not a server error.
            raise AnalysisError(
                "The statistics could not be computed for this study on this data "
                f"({type(e).__name__}). Widen the cohort or use fewer covariates."
            ) from e
        result["issues"] = self._warnings(spec) + result["issues"]
        return clean(result)  # type: ignore[return-value]

    def feasibility(self, spec: StudySpec) -> list[dict[str, Any]]:
        """Try to run the study and say what stops it (errors) or weakens it (warnings).

        The assistant calls this on every study it drafts, so it can tell the
        user a study is not possible, and why, before they try to run it. A
        study that cannot be checked (the database is unreachable) is not
        blocked: running it will report the problem.
        """
        size = self.size_issues(spec)
        if size:
            return size
        try:
            result = self.analysis(spec)
        except StudyError as e:
            return e.issues
        except AnalysisError as e:
            return [issue("error", "cannot_run", str(e))]
        except (DataSourceError, NotImplementedError):
            log.warning("could not try the study", exc_info=True)
            return []
        except Exception:
            log.exception("trying the study failed")
            return [
                issue(
                    "error",
                    "cannot_run",
                    "The study could not be run on this data (unexpected error in the "
                    "analysis). Try a simpler study: fewer covariates or criteria.",
                )
            ]
        return [i for i in result["issues"] if i["level"] == "warning"]

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
            self.feasibility,
        )
        return clean(result)  # type: ignore[return-value]

    def _warnings(self, spec: StudySpec) -> list[dict[str, Any]]:
        """The design warnings for a study. Errors are raised by the repository instead."""
        issues = validate_study(spec, self.mapping, self.repository.dimension_values)
        return [i for i in issues if i["level"] == "warning"]
