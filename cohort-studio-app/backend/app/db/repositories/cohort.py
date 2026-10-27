"""Read cohorts from the database.

CohortRepository is the interface the services and the statistics use. They
get plain Python values and pandas DataFrames back and never see SQL.
SqlCohortRepository implements it for any engine that has a dialect; the
query runner is passed in, so tests can watch every query that is sent.
"""

import math
from typing import Protocol

import pandas as pd

from app.analysis.validation import check_feature_variation, check_small_cells, validate_study
from app.core.exceptions import StudyError
from app.core.mapping import PERSON_SOURCE, Mapping
from app.db import queries
from app.db.dialect import Dialect
from app.db.session import QueryRunner
from app.schemas.study import FeatureSpec, StudySpec, feature_columns

# One dict per eligibility step, in order: {"step": label, "treated": n,
# "control": n}, each n being the patients left after that step and every
# step before it. The first entry is the starting population.
AttritionCounts = list[dict]

# {"feature": name,
#  "columns": [{"column": name,
#               "treated": {"n", "nonzero", "mean", "min", "max"},
#               "control": {...}}, ...],
#  "issues": [warnings about the values, from validation.py]}
FeatureSummary = dict


class CohortRepository(Protocol):
    mapping: Mapping

    def dimension_values(self, source: str, dimension: str) -> list[str]: ...
    def attrition_counts(self, spec: StudySpec) -> AttritionCounts: ...
    def feature_preview(self, feature: FeatureSpec, spec: StudySpec) -> FeatureSummary: ...
    def analysis_table(self, spec: StudySpec) -> pd.DataFrame: ...


class SqlCohortRepository:
    def __init__(self, mapping: Mapping, dialect: Dialect, run: QueryRunner):
        self.mapping = mapping
        self.dialect = dialect
        self.run = run
        # Discovered dimension values, kept for the life of the repository.
        # Restarting the app picks up categories added to the data since.
        self._values: dict[tuple[str, str], list[str]] = {}

    def dimension_values(self, source: str, dimension: str) -> list[str]:
        """The values a user may filter on. Raises LookupError for names not in the mapping."""
        if source == PERSON_SOURCE:
            if dimension not in self.mapping.person.attributes:
                raise LookupError(f"'{dimension}' is not a person attribute")
            table = self.mapping.person.table
        else:
            sources = self.mapping.feature_sources()
            if source not in sources:
                raise LookupError(f"'{source}' is not a source")
            if dimension not in sources[source].dimensions:
                raise LookupError(f"'{dimension}' is not a dimension of {source}")
            pinned = sources[source].dimensions[dimension].values
            if isinstance(pinned, list):
                return list(pinned)
            table = sources[source].table

        key = (source, dimension)
        if key not in self._values:
            query = queries.distinct_values_query(table, dimension, self.dialect)
            self._values[key] = [str(v) for v in self.run(query, {})["value"]]
        return self._values[key]

    def attrition_counts(self, spec: StudySpec) -> AttritionCounts:
        # The cohort is built before an outcome is chosen, so a missing
        # outcome does not stop the counts.
        self._check(spec, ignore={"outcome_count"})
        query, params, labels = queries.attrition_query(spec, self.mapping, self.dialect)
        table = self.run(query, params)

        by_group = {0: [0] * len(labels), 1: [0] * len(labels)}
        for row in table.to_dict("records"):
            by_group[int(row["exposure"])] = [int(row[f"n_{k}"]) for k in range(len(labels))]

        return [
            {"step": label, "treated": by_group[1][k], "control": by_group[0][k]}
            for k, label in enumerate(labels)
        ]

    def feature_preview(self, feature: FeatureSpec, spec: StudySpec) -> FeatureSummary:
        """Summarise one feature's values in the study's cohort, by group.

        A feature already in the study under the same name is replaced, so
        the user can preview an edit before saving it.
        """
        others = [f for f in spec.features if f.name != feature.name]
        # Checked as part of the study, so a preview is refused for the same
        # reasons the analysis would be. A second outcome is allowed: the
        # user may be comparing candidate outcomes before choosing one.
        self._check(
            spec.model_copy(update={"features": [*others, feature]}), ignore={"outcome_count"}
        )
        study = spec.model_copy(update={"features": others})
        query, params = queries.preview_query(study, feature, self.mapping, self.dialect)
        return _summarise(feature, self.run(query, params))

    def analysis_table(self, spec: StudySpec) -> pd.DataFrame:
        """One row per patient in the final cohort; queries.analysis_query lists the columns."""
        self._check(spec)
        query, params = queries.analysis_query(spec, self.mapping, self.dialect)
        return self.run(query, params)

    def _check(self, spec: StudySpec, ignore: set[str] | frozenset[str] = frozenset()) -> None:
        """Refuse to build SQL for a study with errors.

        This is what keeps user input out of the query text: every source,
        dimension, value and measure the study names is matched against the
        mapping, and filter values against the data, before any SQL exists.
        """
        issues = validate_study(spec, self.mapping, self.dimension_values)
        for i in issues:
            if i["level"] == "error" and i["code"] not in ignore:
                raise StudyError(issues)


def _summarise(feature: FeatureSpec, table: pd.DataFrame) -> FeatureSummary:
    issues: list[dict] = []
    sizes = {}
    for arm, group in ((1, "treated"), (0, "control")):
        sizes[group] = int((table["exposure"] == arm).sum())
        issues += check_small_cells({f"{group} patients": sizes[group]})

    columns = []
    for column in feature_columns(feature):
        entry: dict[str, object] = {"column": column}
        for arm, group in ((1, "treated"), (0, "control")):
            values = table.loc[table["exposure"] == arm, column]
            nonzero = int((values != 0).sum())
            entry[group] = {
                "n": sizes[group],
                "nonzero": nonzero,
                "mean": _number(values.mean()),
                "min": _number(values.min()),
                "max": _number(values.max()),
            }
            issues += check_small_cells({f"{group} patients with non-zero {column}": nonzero})
        columns.append(entry)
        issues += check_feature_variation(column, table[column])
    return {"feature": feature.name, "columns": columns, "issues": issues}


def _number(x: object) -> float | None:
    # An empty group gives NaN, which JSON cannot carry.
    if x is None:
        return None
    value = float(x)  # type: ignore[arg-type]
    if math.isnan(value):
        return None
    return value
