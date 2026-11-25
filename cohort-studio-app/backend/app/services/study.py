"""The study operations behind the MCP tools: metadata, check, attrition and analysis.

Each method returns a plain dict ready to be sent as JSON (NaN and infinity
already replaced by None).
"""

import logging
from typing import Any

import numpy as np

from app.analysis.outcome_models import implied_model
from app.analysis.runner import run_analysis
from app.analysis.validation import check_cohort_size, check_small_cells, validate_study
from app.core.exceptions import AnalysisError
from app.core.jsonsafe import clean
from app.db.repositories.cohort import CohortRepository
from app.schemas.study import StudySpec
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

        Cheap enough to call on every draft, so problems and the model choice
        show before anything runs.
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

    def _warnings(self, spec: StudySpec) -> list[dict[str, Any]]:
        """The design warnings for a study. Errors are raised by the repository instead."""
        issues = validate_study(spec, self.mapping, self.repository.dimension_values)
        return [i for i in issues if i["level"] == "warning"]
