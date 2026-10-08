"""Tests for the SQL text itself: names, bound values and coverage arithmetic.

The values the SQL produces are checked against a database in
test_repository.py; these tests need no database.
"""
from datetime import date

import pytest

from cohort_studio import sql
from cohort_studio.dialect import DuckDbDialect
from cohort_studio.features import FeatureSpec, StudySpec
from cohort_studio.mapping import Coverage, Source

D = DuckDbDialect()


def study(**overrides) -> StudySpec:
    body = {
        "exposure": "program_a",
        "person_filters": {"gender": ["F"]},
        "features": [
            {"name": "scdf_pre", "label": "x", "source": "ed_episodes",
             "filters": {"mode_of_arrival": ["SCDF", "Own transport"]},
             "window": {"from": -365, "to": -1, "unit": "days"},
             "aggregation": "count", "role": "covariate"},
            {"name": "ed_post", "label": "y", "source": "ed_episodes",
             "window": {"from": 1, "to": 365, "unit": "days"},
             "aggregation": "count", "role": "outcome"},
        ],
    }
    body.update(overrides)
    return StudySpec.model_validate(body)


def test_values_are_bound_never_written_into_the_sql(mapping):
    query, params = sql.analysis_query(study(), mapping, D)
    assert "SCDF" not in query
    assert "Own transport" not in query
    assert "'F'" not in query
    assert {"SCDF", "Own transport", "F"} <= set(params.values())
    for key in params:
        assert f"${key}" in query


def test_each_feature_is_one_cte(mapping):
    query, _ = sql.analysis_query(study(), mapping, D)
    assert query.count("f_scdf_pre AS (") == 1
    assert query.count("f_ed_post AS (") == 1
    assert query.count("LEFT JOIN f_") == 2


@pytest.mark.parametrize("text", ["ed; DROP TABLE x", "a b", "x--", "'q'", "a.b.c.d", "", None])
def test_unsafe_names_are_refused(text):
    with pytest.raises(ValueError):
        sql.name(text)


def test_a_mapping_that_skipped_validation_still_cannot_inject(mapping):
    # model_construct skips pydantic checks, as code building a Mapping by
    # hand might. The generator must refuse the name on its own.
    bad = mapping.model_copy(deep=True)
    bad.sources[0] = Source.model_construct(**{**bad.sources[0].__dict__,
                                               "table": "ed_episodes; DROP TABLE master_patient"})
    with pytest.raises(ValueError, match="not a safe SQL name"):
        sql.analysis_query(study(), bad, D)


def test_distinct_values_query_casts_to_text(mapping):
    query = sql.distinct_values_query("ed_episodes", "triage_level", D)
    assert query.startswith("SELECT DISTINCT CAST(triage_level AS VARCHAR)")


@pytest.mark.parametrize("granularity, start, end, expected", [
    ("day", date(2018, 1, 1), date(2025, 12, 31), (date(2018, 1, 1), date(2026, 1, 1))),
    # Only whole years count: a table starting in March has an incomplete first year.
    ("year", date(2018, 1, 1), date(2025, 12, 31), (2018, 2026)),
    ("year", date(2018, 3, 1), date(2025, 6, 30), (2019, 2025)),
    # Months are numbered year * 12 + month - 1.
    ("month", date(2018, 1, 1), date(2025, 12, 31), (2018 * 12, 2025 * 12 + 12)),
    ("month", date(2018, 1, 10), date(2025, 12, 30), (2018 * 12 + 1, 2025 * 12 + 11)),
    ("day", None, None, (None, None)),
])
def test_coverage_bounds(granularity, start, end, expected):
    source = Source(name="s", table="t", id="i", date="d", granularity=granularity,
                    coverage=Coverage(start=start, end=end))
    assert sql.coverage_bounds(source) == expected


@pytest.mark.parametrize("window, years", [
    ({"from": 1, "to": 365, "unit": "days"}, 365 / 365.25),
    ({"from": 1, "to": 12, "unit": "months"}, 1.0),
    ({"from": -12, "to": -1, "unit": "months"}, 1.0),
    ({"from": 1, "to": 2, "unit": "years"}, 2.0),
    # Month 0 is the index day alone.
    ({"from": 0, "to": 12, "unit": "months"}, 1.0 + 1 / 365.25),
])
def test_window_years(window, years):
    feature = FeatureSpec.model_validate({"name": "x", "label": "x", "source": "ed_episodes",
                                          "window": window, "aggregation": "count",
                                          "role": "outcome"})
    assert sql.window_years(feature) == pytest.approx(years)


@pytest.mark.parametrize("k, unit, first, last", [
    (1, "months", 1, 1), (-1, "months", -1, -1), (0, "months", 0, 0),
    (1, "years", 1, 12), (2, "years", 13, 24), (-1, "years", -12, -1),
])
def test_units_in_months(k, unit, first, last):
    assert sql.first_month(k, unit) == first
    assert sql.last_month(k, unit) == last
