"""Tests for validator.py: every rejection rule, the design warnings and the data checks."""

import pandas as pd
import pytest

from app.analysis.validation import (
    check_events_per_covariate,
    check_feature_variation,
    check_small_cells,
    validate_study,
)
from app.schemas.study import StudySpec


def feature(**overrides) -> dict:
    """A valid covariate: ED attendances in the 365 days before index."""
    spec = {
        "name": "ed_12m_pre",
        "label": "ED attendances, 12 months pre-index",
        "source": "ed_episodes",
        "window": {"from": -365, "to": -1, "unit": "days"},
        "aggregation": "count",
        "role": "covariate",
    }
    spec.update(overrides)
    return spec


def condition(**overrides) -> dict:
    """A valid covariate on the year-granularity condition table."""
    spec = feature(
        name="diabetes_pre",
        label="Diabetes before the index year",
        source="condition",
        filters={"condition_name": ["diabetes"]},
        window={"from": -50, "to": -1, "unit": "years"},
        aggregation="binary",
    )
    spec.update(overrides)
    return spec


OUTCOME = feature(
    name="ed_12m_post",
    label="ED attendances, 12 months post-index",
    window={"from": 1, "to": 365, "unit": "days"},
    role="outcome",
)


def study(*features: dict, outcome: dict | None = OUTCOME, **overrides) -> StudySpec:
    """A valid study around the given features, with the default outcome unless replaced."""
    all_features = list(features)
    if outcome is not None:
        all_features.append(outcome)
    body = {
        "exposure": "program_a",
        "person_covariates": ["age", "gender"],
        "features": all_features,
    }
    body.update(overrides)
    return StudySpec.model_validate(body)


def codes(issues: list[dict], level: str = "error") -> list[str]:
    result = []
    for i in issues:
        if i["level"] == level:
            result.append(i["code"])
    return result


# ------------------------------------------------------------ valid study


def test_valid_study_has_no_issues(mapping):
    s = study(
        feature(),
        condition(),
        feature(
            name="ed_scdf_12m_pre", filters={"mode_of_arrival": ["SCDF"]}, aggregation="binary"
        ),
        feature(name="los_mean_12m_pre", aggregation="mean", measure="los_hours"),
        feature(
            name="ed_quarterly_pre",
            window={"from": -24, "to": -1, "unit": "months"},
            periodise={"grain": "quarter", "n": 8},
        ),
        condition(
            name="no_asthma",
            filters={"condition_name": ["asthma"]},
            role="inclusion",
            keep_if={"op": "==", "value": 0},
        ),
        age_min=40,
        age_max=85,
        person_filters={"gender": ["F"]},
    )
    assert validate_study(s, mapping) == []


# --------------------------------------------- rule: covariate look-ahead


@pytest.mark.parametrize(
    "window",
    [
        {"from": -365, "to": 0, "unit": "days"},
        {"from": -365, "to": 30, "unit": "days"},
        {"from": -12, "to": 0, "unit": "months"},
        {"from": 1, "to": 365, "unit": "days"},
    ],
)
def test_covariate_window_reaching_index_is_rejected(mapping, window):
    issues = validate_study(study(feature(window=window)), mapping)
    assert "covariate_lookahead" in codes(issues)


def test_covariate_window_ending_the_day_before_index_is_accepted(mapping):
    issues = validate_study(study(feature(window={"from": -30, "to": -1, "unit": "days"})), mapping)
    assert codes(issues) == []


def test_diagnosis_in_the_index_year_is_rejected_as_lookahead(mapping):
    # The cohort-poc bug: a diagnosis any time in the index year counted as baseline,
    # including diagnoses made after enrollment.
    s = study(condition(window={"from": -50, "to": 0, "unit": "years"}))
    assert "covariate_lookahead" in codes(validate_study(s, mapping))


# ------------------------------------ rule: same events as covariate and outcome


def test_same_events_as_covariate_and_outcome_are_rejected(mapping):
    window = {"from": -365, "to": -1, "unit": "days"}
    covariate = feature(
        name="scdf_pre",
        filters={"mode_of_arrival": ["SCDF", "Own"]},
        window=window,
        aggregation="binary",
    )
    # Same filter written in a different order, different aggregation: still the same events.
    outcome = feature(
        name="scdf_out",
        filters={"mode_of_arrival": ["Own", "SCDF"]},
        window=window,
        aggregation="count",
        role="outcome",
    )
    issues = validate_study(study(covariate, outcome=outcome), mapping)
    assert "same_feature_covariate_and_outcome" in codes(issues)


@pytest.mark.parametrize(
    "change",
    [
        {"filters": {"mode_of_arrival": ["Own"]}},
        {"window": {"from": -180, "to": -1, "unit": "days"}},
        {
            "source": "condition",
            "window": {"from": -1, "to": -1, "unit": "years"},
            "filters": {"condition_name": ["copd"]},
        },
    ],
)
def test_different_events_are_not_the_same_feature(mapping, change):
    covariate = feature(name="scdf_pre", filters={"mode_of_arrival": ["SCDF"]})
    outcome = feature(name="scdf_out", filters={"mode_of_arrival": ["SCDF"]}, role="outcome")
    outcome.update(change)
    issues = validate_study(study(covariate, outcome=outcome), mapping)
    assert "same_feature_covariate_and_outcome" not in codes(issues)


# ------------------------------- rule: window finer than source granularity


@pytest.mark.parametrize("unit", ["days", "months"])
def test_window_finer_than_a_year_source_is_rejected(mapping, unit):
    s = study(condition(window={"from": -365, "to": -1, "unit": unit}))
    assert "window_finer_than_source" in codes(validate_study(s, mapping))


@pytest.mark.parametrize("grain", ["month", "quarter"])
def test_periods_finer_than_a_year_source_are_rejected(mapping, grain):
    n = 24 if grain == "month" else 8
    s = study(
        condition(
            window={"from": -2, "to": -1, "unit": "years"}, periodise={"grain": grain, "n": n}
        )
    )
    assert "window_finer_than_source" in codes(validate_study(s, mapping))


def test_time_to_first_event_on_a_year_source_is_rejected(mapping):
    outcome = condition(
        name="copd_onset",
        filters={"condition_name": ["copd"]},
        window={"from": 1, "to": 5, "unit": "years"},
        aggregation="time_to_first",
        role="outcome",
    )
    issues = validate_study(study(outcome=outcome), mapping)
    assert "window_finer_than_source" in codes(issues)


def test_year_periods_on_a_year_source_are_accepted(mapping):
    s = study(
        condition(
            window={"from": -3, "to": -1, "unit": "years"}, periodise={"grain": "year", "n": 3}
        )
    )
    assert codes(validate_study(s, mapping)) == []


# --------------------------------------- rule: inclusion uses post-index data


@pytest.mark.parametrize(
    "window",
    [
        {"from": 1, "to": 90, "unit": "days"},
        {"from": -365, "to": 0, "unit": "days"},
        {"from": -5, "to": 0, "unit": "years"},
    ],
)
def test_inclusion_criterion_using_post_index_data_is_rejected(mapping, window):
    criterion = feature(
        name="ed_criterion",
        window=window,
        aggregation="binary",
        role="inclusion",
        keep_if={"op": "==", "value": 1},
    )
    assert "inclusion_post_index" in codes(validate_study(study(criterion), mapping))


def test_inclusion_criterion_before_index_is_accepted(mapping):
    criterion = condition(name="has_diabetes", role="inclusion", keep_if={"op": "==", "value": 1})
    assert codes(validate_study(study(criterion), mapping)) == []


# ------------------------------------------------ references to the mapping


def test_unknown_exposure_is_rejected(mapping):
    assert "unknown_exposure" in codes(validate_study(study(exposure="program_b"), mapping))


def test_unknown_source_is_rejected(mapping):
    s = study(feature(source="pharmacy"))
    assert "unknown_source" in codes(validate_study(s, mapping))


def test_unknown_dimension_is_rejected(mapping):
    s = study(feature(filters={"ward": ["A"]}))
    assert "unknown_dimension" in codes(validate_study(s, mapping))


def test_values_of_auto_dimensions_are_checked_with_the_lookup(mapping):
    calls = []

    def lookup(source: str, column: str) -> list[str]:
        calls.append((source, column))
        return ["SCDF", "Own transport"]

    good = study(feature(filters={"mode_of_arrival": ["SCDF"]}))
    bad = study(feature(filters={"mode_of_arrival": ["Helicopter"]}))
    assert codes(validate_study(good, mapping, lookup)) == []
    assert "unknown_dimension_value" in codes(validate_study(bad, mapping, lookup))
    assert calls[0] == ("ed_episodes", "mode_of_arrival")


def test_values_pinned_in_the_config_are_checked_without_a_lookup(mapping):
    mapping.sources[0].dimensions["triage_level"].values = ["1", "2", "3"]
    good = study(feature(filters={"triage_level": [1, 2]}))
    bad = study(feature(filters={"triage_level": ["9"]}))
    assert codes(validate_study(good, mapping)) == []
    assert "unknown_dimension_value" in codes(validate_study(bad, mapping))


def test_unknown_measure_is_rejected(mapping):
    s = study(feature(aggregation="sum", measure="cost"))
    assert "unknown_measure" in codes(validate_study(s, mapping))


def test_aggregation_not_allowed_on_measure_is_rejected(mapping):
    mapping.sources[0].measures["los_hours"].agg = ["mean"]
    s = study(feature(aggregation="sum", measure="los_hours"))
    assert "aggregation_not_allowed" in codes(validate_study(s, mapping))


def test_unknown_person_attribute_is_rejected(mapping):
    for s in [
        study(person_filters={"religion": ["x"]}),
        study(person_covariates=["age", "income"]),
    ]:
        assert "unknown_person_attribute" in codes(validate_study(s, mapping))


def test_person_filter_values_are_checked_with_the_lookup(mapping):
    def lookup(source: str, column: str) -> list[str]:
        assert (source, column) == ("person", "gender")
        return ["F", "M"]

    s = study(person_filters={"gender": ["X"]})
    assert "unknown_dimension_value" in codes(validate_study(s, mapping, lookup))


# ------------------------------------------------ roles and aggregations


def test_study_without_an_outcome_is_rejected(mapping):
    assert "outcome_count" in codes(validate_study(study(outcome=None), mapping))


def test_study_with_two_outcomes_is_rejected(mapping):
    second = feature(
        name="ed_6m_post", window={"from": 1, "to": 180, "unit": "days"}, role="outcome"
    )
    assert "outcome_count" in codes(validate_study(study(second), mapping))


def test_time_to_first_as_covariate_is_rejected(mapping):
    s = study(feature(aggregation="time_to_first"))
    assert "aggregation_not_allowed" in codes(validate_study(s, mapping))


def test_measure_outcome_is_rejected(mapping):
    outcome = feature(
        name="los_post",
        window={"from": 1, "to": 365, "unit": "days"},
        aggregation="sum",
        measure="los_hours",
        role="outcome",
    )
    issues = validate_study(study(outcome=outcome), mapping)
    assert "outcome_aggregation_unsupported" in codes(issues)


@pytest.mark.parametrize("aggregation", ["binary", "time_to_first"])
def test_periodised_outcome_that_is_not_a_count_is_rejected(mapping, aggregation):
    outcome = feature(
        name="ed_quarterly_post",
        window={"from": 1, "to": 24, "unit": "months"},
        aggregation=aggregation,
        periodise={"grain": "quarter", "n": 8},
        role="outcome",
    )
    issues = validate_study(study(outcome=outcome), mapping)
    assert "outcome_aggregation_unsupported" in codes(issues)


def test_periodised_count_outcome_is_accepted(mapping):
    outcome = feature(
        name="ed_quarterly_post",
        window={"from": 1, "to": 24, "unit": "months"},
        periodise={"grain": "quarter", "n": 8},
        role="outcome",
    )
    assert validate_study(study(outcome=outcome), mapping) == []


def test_periodised_inclusion_criterion_is_rejected(mapping):
    criterion = feature(
        name="ed_criterion",
        window={"from": -24, "to": -1, "unit": "months"},
        periodise={"grain": "quarter", "n": 8},
        role="inclusion",
        keep_if={"op": ">=", "value": 1},
    )
    assert "periodise_not_allowed" in codes(validate_study(study(criterion), mapping))


# ------------------------------------------------------- periodised windows


def test_periodised_day_window_is_rejected(mapping):
    s = study(
        feature(
            window={"from": -730, "to": -1, "unit": "days"}, periodise={"grain": "quarter", "n": 8}
        )
    )
    assert "periodise_window_mismatch" in codes(validate_study(s, mapping))


@pytest.mark.parametrize(
    "window",
    [
        {"from": -11, "to": 0, "unit": "months"},
        {"from": 0, "to": 11, "unit": "months"},
        {"from": -6, "to": 5, "unit": "months"},
    ],
)
def test_periodised_window_containing_the_index_day_is_rejected(mapping, window):
    outcome = feature(
        name="ed_q_post", window=window, periodise={"grain": "quarter", "n": 4}, role="outcome"
    )
    issues = validate_study(study(outcome=outcome), mapping)
    assert "periodise_window_mismatch" in codes(issues)


def test_periodised_window_of_the_wrong_length_is_rejected(mapping):
    s = study(
        feature(
            window={"from": -12, "to": -1, "unit": "months"}, periodise={"grain": "quarter", "n": 8}
        )
    )
    assert "periodise_window_mismatch" in codes(validate_study(s, mapping))


# --------------------------------------------------------------- names


@pytest.mark.parametrize("name", ["age", "exposure", "patient_id", "gender", "person_years"])
def test_feature_named_like_a_fixed_column_is_rejected(mapping, name):
    s = study(feature(name=name))
    assert "reserved_feature_name" in codes(validate_study(s, mapping))


def test_periodised_columns_clashing_with_another_feature_are_rejected(mapping):
    quarterly = feature(
        name="ed_q",
        window={"from": -24, "to": -1, "unit": "months"},
        periodise={"grain": "quarter", "n": 8},
    )
    s = study(quarterly, feature(name="ed_q_p3"))
    assert "column_name_clash" in codes(validate_study(s, mapping))


def test_time_to_first_columns_clashing_with_a_fixed_column_are_rejected(mapping):
    # time_to_first adds <name>_days and <name>_event, which another
    # feature could also be called.
    outcome = feature(
        name="tte",
        window={"from": 1, "to": 365, "unit": "days"},
        aggregation="time_to_first",
        role="outcome",
    )
    s = study(feature(name="tte_event"), outcome=outcome)
    assert "column_name_clash" in codes(validate_study(s, mapping))


def test_duplicate_feature_names_are_rejected(mapping):
    s = study(feature(), feature(aggregation="binary"))
    assert "duplicate_feature_name" in codes(validate_study(s, mapping))


# ---------------------------------------------------------- outcome timing


def test_time_to_event_outcome_starting_at_index_is_rejected(mapping):
    outcome = feature(
        name="tte",
        window={"from": 0, "to": 365, "unit": "days"},
        aggregation="time_to_first",
        role="outcome",
    )
    issues = validate_study(study(outcome=outcome), mapping)
    assert "outcome_window_before_index" in codes(issues)


def test_count_outcome_starting_before_index_is_a_warning(mapping):
    outcome = feature(
        name="ed_around_index", window={"from": -30, "to": 365, "unit": "days"}, role="outcome"
    )
    issues = validate_study(study(outcome=outcome), mapping)
    assert codes(issues) == []
    assert codes(issues, "warning") == ["outcome_window_before_index"]


def test_all_problems_are_reported_together(mapping):
    s = study(
        feature(filters={"ward": ["A"]}, window={"from": -30, "to": 0, "unit": "days"}),
        exposure="program_b",
    )
    assert set(codes(validate_study(s, mapping))) == {
        "unknown_dimension",
        "covariate_lookahead",
        "unknown_exposure",
    }


# ------------------------------------------------------------- data checks


def test_too_few_events_per_coefficient_warns():
    issues = check_events_per_covariate(events=30, parameters=10)
    assert codes(issues, "warning") == ["low_events_per_covariate"]


@pytest.mark.parametrize("events, parameters", [(100, 10), (5, 0)])
def test_enough_events_per_coefficient_is_quiet(events, parameters):
    assert check_events_per_covariate(events=events, parameters=parameters) == []


@pytest.mark.parametrize("values", [[0] * 100, [None] * 10, [3.5] * 20 + [None]])
def test_constant_feature_warns(values):
    issues = check_feature_variation("dx_copd", pd.Series(values, dtype="float"))
    assert codes(issues, "warning") == ["constant_feature"]


def test_near_constant_feature_warns():
    issues = check_feature_variation("dx_copd", pd.Series([0] * 995 + [1] * 5))
    assert codes(issues, "warning") == ["near_constant_feature"]


def test_varied_feature_is_quiet():
    assert check_feature_variation("dx_copd", pd.Series([0] * 90 + [1] * 10)) == []


def test_small_cells_warn_and_zero_does_not():
    counts = {"treated with event": 3, "controls with event": 0, "treated": 5, "controls": 120}
    issues = check_small_cells(counts)
    assert len(issues) == 1
    assert "treated with event" in issues[0]["message"]


def test_suppression_threshold_can_be_changed():
    assert len(check_small_cells({"cell": 8}, threshold=10)) == 1
