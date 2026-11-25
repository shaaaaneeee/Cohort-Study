"""Read cohorts from the database.

CohortRepository is the interface the services and the statistics use. They
get plain Python values and pandas DataFrames back and never see SQL.
SqlCohortRepository implements it for any engine that has a dialect; the
query runner is passed in, so tests can watch every query that is sent.
"""

from typing import Protocol

import pandas as pd

from app.analysis.validation import validate_study
from app.core.exceptions import StudyError
from app.core.mapping import PERSON_SOURCE, Mapping
from app.db import queries
from app.db.dialect import Dialect
from app.db.session import QueryRunner
from app.schemas.study import StudySpec

# One dict per eligibility step, in order: {"step": label, "treated": n,
# "control": n}, each n being the patients left after that step and every
# step before it. The first entry is the starting population.
AttritionCounts = list[dict]

# {"feature": name,
#  "columns": [{"column": name,
#               "treated": {"n", "nonzero", "mean", "min", "max"},
#               "control": {...}}, ...],
#  "issues": [warnings about the values, from validation.py]}


class CohortRepository(Protocol):
    mapping: Mapping

    def dimension_values(self, source: str, dimension: str) -> list[str]: ...
    def attrition_counts(self, spec: StudySpec) -> AttritionCounts: ...
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
