"""Tests for the feature and study schema: shape checks that need no mapping."""

import pytest
from pydantic import ValidationError

from app.schemas.study import FeatureSpec, StudySpec, feature_columns


def feature(**overrides) -> dict:
    spec = {
        "name": "ed_scdf_12m_pre",
        "label": "SCDF-conveyed ED attendances, 12 months pre-index",
        "source": "ed_episodes",
        "filters": {"mode_of_arrival": ["SCDF"]},
        "window": {"anchor": "index", "from": -365, "to": -1, "unit": "days"},
        "aggregation": "count",
        "periodise": None,
        "role": "covariate",
    }
    spec.update(overrides)
    return spec


def test_example_from_the_brief_parses():
    f = FeatureSpec.model_validate(feature())
    assert f.window.from_ == -365
    assert f.filters == {"mode_of_arrival": ["SCDF"]}


def test_window_is_written_back_with_from_not_from_():
    f = FeatureSpec.model_validate(feature())
    assert f.model_dump()["window"]["from"] == -365


def test_window_from_after_to_is_refused():
    with pytest.raises(ValidationError, match="after"):
        FeatureSpec.model_validate(feature(window={"from": -1, "to": -365, "unit": "days"}))


def test_empty_filter_list_is_refused():
    with pytest.raises(ValidationError):
        FeatureSpec.model_validate(feature(filters={"mode_of_arrival": []}))


def test_numeric_filter_values_are_read_as_text():
    f = FeatureSpec.model_validate(feature(filters={"triage_level": [1, 2]}))
    assert f.filters == {"triage_level": ["1", "2"]}


@pytest.mark.parametrize("name", ["Ed_visits", "1ed", "ed-visits", "ed; drop table x", ""])
def test_unsafe_feature_names_are_refused(name):
    with pytest.raises(ValidationError):
        FeatureSpec.model_validate(feature(name=name))


@pytest.mark.parametrize(
    "field, value",
    [
        ("source", "ed_episodes; --"),
        ("filters", {"mode_of_arrival = 'x' OR 1=1 --": ["SCDF"]}),
    ],
)
def test_unsafe_source_and_dimension_names_are_refused(field, value):
    with pytest.raises(ValidationError):
        FeatureSpec.model_validate(feature(**{field: value}))


def test_unknown_aggregation_is_refused():
    with pytest.raises(ValidationError):
        FeatureSpec.model_validate(feature(aggregation="median"))


def test_measure_aggregation_without_measure_is_refused():
    with pytest.raises(ValidationError, match="needs a measure"):
        FeatureSpec.model_validate(feature(aggregation="mean"))


def test_count_with_measure_is_refused():
    with pytest.raises(ValidationError, match="does not use a measure"):
        FeatureSpec.model_validate(feature(measure="los_hours"))


def test_inclusion_without_keep_if_is_refused():
    with pytest.raises(ValidationError, match="needs keep_if"):
        FeatureSpec.model_validate(feature(role="inclusion"))


def test_keep_if_outside_inclusion_is_refused():
    with pytest.raises(ValidationError, match="only used by inclusion"):
        FeatureSpec.model_validate(feature(keep_if={"op": ">=", "value": 1}))


def test_single_period_is_refused():
    with pytest.raises(ValidationError):
        FeatureSpec.model_validate(feature(periodise={"grain": "quarter", "n": 1}))


def test_unknown_field_is_refused():
    with pytest.raises(ValidationError):
        FeatureSpec.model_validate(feature(colour="blue"))


def test_inverted_age_range_is_refused():
    with pytest.raises(ValidationError, match="greater than"):
        StudySpec.model_validate({"exposure": "program_a", "age_min": 80, "age_max": 40})


@pytest.mark.parametrize(
    "overrides, columns",
    [
        ({}, ["ed_scdf_12m_pre"]),
        (
            {
                "window": {"from": -12, "to": -1, "unit": "months"},
                "periodise": {"grain": "quarter", "n": 4},
            },
            [
                "ed_scdf_12m_pre_p1",
                "ed_scdf_12m_pre_p2",
                "ed_scdf_12m_pre_p3",
                "ed_scdf_12m_pre_p4",
            ],
        ),
        (
            {
                "aggregation": "time_to_first",
                "role": "outcome",
                "window": {"from": 1, "to": 365, "unit": "days"},
            },
            ["ed_scdf_12m_pre_days", "ed_scdf_12m_pre_event"],
        ),
    ],
)
def test_feature_columns(overrides, columns):
    assert feature_columns(FeatureSpec.model_validate(feature(**overrides))) == columns


def test_study_seed_defaults_to_zero_and_must_be_non_negative():
    assert StudySpec.model_validate({"exposure": "program_a"}).seed == 0
    with pytest.raises(ValidationError):
        StudySpec.model_validate({"exposure": "program_a", "seed": -1})
