"""Build cohorts from a small hand-made database and check every value by hand.

The data is in support.hand_made_tables(). Every treated patient enrols on
15 June 2021, so every control is also indexed on that date and the expected
values below can be worked out on paper.
"""
import pandas as pd
import pytest

from cohort_studio.features import FeatureSpec, StudySpec
from cohort_studio.mapping import Source
from cohort_studio.repository import SqlRepository, StudyError
from tests.support import build_database, hand_made_tables, repository_for

INDEX = pd.Timestamp("2021-06-15")


@pytest.fixture
def repo(tmp_path, mapping) -> SqlRepository:
    path = tmp_path / "hand.duckdb"
    build_database(path, hand_made_tables())
    return repository_for(path, mapping)


def ed(name: str, start: int, end: int, unit: str = "days", role: str = "covariate", **extra) -> dict:
    spec = {"name": name, "label": name, "source": "ed_episodes",
            "window": {"from": start, "to": end, "unit": unit},
            "aggregation": "count", "role": role}
    spec.update(extra)
    return spec


def dx(name: str, condition: str, **extra) -> dict:
    spec = {"name": name, "label": f"{condition} before the index year", "source": "condition",
            "filters": {"condition_name": [condition]},
            "window": {"from": -50, "to": -1, "unit": "years"},
            "aggregation": "binary", "role": "covariate"}
    spec.update(extra)
    return spec


OUTCOME = ed("ed_post", 1, 365, role="outcome")


def study(*features: dict, outcome: dict | None = OUTCOME, **overrides) -> StudySpec:
    all_features = list(features)
    if outcome is not None:
        all_features.append(outcome)
    body = {"exposure": "program_a", "features": all_features}
    body.update(overrides)
    return StudySpec.model_validate(body)


def by_patient(table: pd.DataFrame, column: str) -> dict:
    return dict(zip(table["patient_id"], table[column]))


# ------------------------------------------------------------------ cohort

def test_cohort_membership_index_dates_and_ages(repo):
    table = repo.analysis_table(study())
    assert list(table["patient_id"]) == ["T1", "T2", "C1", "C2"]   # treated first
    assert by_patient(table, "exposure") == {"T1": 1, "T2": 1, "C1": 0, "C2": 0}
    # T1's re-enrolment does not move the index date, and every control
    # draws a treated index date, which here can only be 15 June 2021.
    assert set(table["index_date"]) == {INDEX}
    assert by_patient(table, "age") == {"T1": 60, "T2": 50, "C1": 71, "C2": 17}
    assert by_patient(table, "gender") == {"T1": "F", "T2": "M", "C1": "F", "C2": "M"}


def test_person_years_is_the_outcome_window_length(repo):
    table = repo.analysis_table(study())
    assert table["person_years"].iloc[0] == pytest.approx(365 / 365.25)


# ------------------------------------------------------- windows and filters

def test_day_window_includes_both_ends_and_excludes_the_index_day(repo):
    table = repo.analysis_table(study(ed("ed_pre", -365, -1)))
    # T1: day -365 and day -1 count; day -366 and day 0 do not.
    assert by_patient(table, "ed_pre") == {"T1": 2, "T2": 0, "C1": 3, "C2": 1}
    # Outcome days 1 to 365: two visits on day 1 and one on day 365, not day 366.
    assert by_patient(table, "ed_post")["T1"] == 3


def test_patients_without_events_are_zero_not_dropped(repo):
    table = repo.analysis_table(study(ed("ed_pre", -365, -1),
                                      ed("los_mean", -365, -1, aggregation="mean", measure="los_hours")))
    t2 = table[table["patient_id"] == "T2"].iloc[0]
    assert t2["ed_pre"] == 0
    assert t2["ed_post"] == 0
    assert t2["los_mean"] == 0


def test_filters_keep_only_matching_events(repo):
    table = repo.analysis_table(study(
        ed("scdf_pre", -365, -1, filters={"mode_of_arrival": ["SCDF"]}),
        ed("scdf_p2_pre", -365, -1, filters={"mode_of_arrival": ["SCDF"], "triage_level": ["P2"]}),
        ed("any_two_pre", -365, -1, filters={"triage_level": ["P2", "P3"]})))
    assert by_patient(table, "scdf_pre") == {"T1": 1, "T2": 0, "C1": 1, "C2": 0}
    assert by_patient(table, "scdf_p2_pre") == {"T1": 1, "T2": 0, "C1": 0, "C2": 0}
    assert by_patient(table, "any_two_pre") == {"T1": 2, "T2": 0, "C1": 3, "C2": 1}


def test_each_aggregation(repo):
    table = repo.analysis_table(study(
        ed("any_pre", -365, -1, aggregation="binary"),
        ed("los_sum", -365, -1, aggregation="sum", measure="los_hours"),
        ed("los_mean", -365, -1, aggregation="mean", measure="los_hours"),
        ed("los_max", -365, -1, aggregation="max", measure="los_hours"),
        ed("ed_rate", -365, -1, aggregation="rate"),
        outcome=ed("days_post", 1, 365, role="outcome", aggregation="distinct_count")))
    t1 = table[table["patient_id"] == "T1"].iloc[0]
    assert t1["any_pre"] == 1
    assert t1["los_sum"] == 6.0
    assert t1["los_mean"] == 3.0
    assert t1["los_max"] == 4.0
    assert t1["ed_rate"] == pytest.approx(2 / (365 / 365.25))
    # Visits on day 1 (two), day 365: three visits on two distinct days.
    assert t1["days_post"] == 2
    assert by_patient(table, "los_mean")["C1"] == 4.0


def test_condition_diagnosed_in_the_index_year_is_not_baseline(repo):
    # The cohort-poc bug: a diagnosis anywhere in the index year counted as
    # baseline. With year granularity "before index" means up to the year before.
    table = repo.analysis_table(study(dx("dx_diabetes", "diabetes"), dx("dx_copd", "copd"),
                                      dx("dx_asthma", "asthma")))
    assert by_patient(table, "dx_diabetes") == {"T1": 1, "T2": 0, "C1": 0, "C2": 0}
    assert by_patient(table, "dx_copd") == {"T1": 0, "T2": 0, "C1": 0, "C2": 0}
    assert by_patient(table, "dx_asthma") == {"T1": 0, "T2": 0, "C1": 1, "C2": 0}


def test_periodised_feature_has_one_column_per_period(repo):
    table = repo.analysis_table(study(ed("ed_q", -12, -1, unit="months",
                                         periodise={"grain": "quarter", "n": 4})))
    columns = ["ed_q_p1", "ed_q_p2", "ed_q_p3", "ed_q_p4"]
    rows = table.set_index("patient_id")[columns]
    # Periods start 12, 9, 6 and 3 months before 15 June 2021.
    assert list(rows.loc["T1"]) == [1, 0, 0, 1]   # 15 Jun 2020 opens p1; 14 Jun 2021 closes p4
    assert list(rows.loc["C1"]) == [0, 0, 1, 2]   # 1 Jan in p3; 31 May and 1 Jun in p4
    assert list(rows.loc["C2"]) == [0, 0, 1, 0]
    assert list(rows.loc["T2"]) == [0, 0, 0, 0]


def test_time_to_first_event_and_censoring(repo):
    table = repo.analysis_table(study(outcome=ed("first_ed", 1, 365, role="outcome",
                                                 aggregation="time_to_first")))
    assert by_patient(table, "first_ed_days") == {"T1": 1, "T2": 365, "C1": 365, "C2": 365}
    assert by_patient(table, "first_ed_event") == {"T1": 1, "T2": 0, "C1": 0, "C2": 0}
    assert "person_years" not in table.columns


@pytest.mark.parametrize("start, end, unit, expected", [
    (1, 1, "months", 2),    # 16 June to 15 July: the two visits on day 1
    (1, 12, "months", 3),   # 16 June 2021 to 15 June 2022
    (1, 1, "years", 3),     # the same twelve months
    (0, 0, "months", 1),    # the index day only
])
def test_month_and_year_windows_after_index_start_the_next_day(repo, start, end, unit, expected):
    table = repo.analysis_table(study(outcome=ed("ed_after", start, end, unit=unit, role="outcome")))
    assert by_patient(table, "ed_after")["T1"] == expected


def test_month_source_uses_calendar_months(repo):
    # The same ED table declared as month granularity. "The month before
    # index" is then calendar May 2021: the visit on 1 June is in the index
    # month and may be after the index date, so it must not count.
    repo.mapping.sources.append(Source(name="ed_monthly", table="ed_episodes", id="patient_id",
                                       date="attendance_date", granularity="month"))
    month = ed("month_before", -1, -1, unit="months")
    table = repo.analysis_table(study(dict(month, source="ed_monthly"),
                                      dict(month, name="day_based")))
    assert by_patient(table, "month_before")["C1"] == 1      # 31 May only
    assert by_patient(table, "day_based")["C1"] == 2         # 15 May to 14 June: both


# ---------------------------------------------------- eligibility and attrition

def test_attrition_counts_every_step(repo):
    s = study(dx("has_diabetes", "diabetes", role="inclusion", keep_if={"op": "==", "value": 1}),
              age_min=18)
    assert repo.attrition_counts(s) == [
        {"step": "Starting population", "treated": 3, "control": 2},
        {"step": "Has a patient record", "treated": 2, "control": 2},
        {"step": "Aged 18 or over at index date", "treated": 2, "control": 1},
        {"step": "Data covers every look-back and follow-up window", "treated": 2, "control": 1},
        {"step": "diabetes before the index year", "treated": 1, "control": 0},
    ]
    table = repo.analysis_table(s)
    assert list(table["patient_id"]) == ["T1"]
    # An inclusion criterion filters the cohort; it is not a column.
    assert "has_diabetes" not in table.columns


def test_attrition_works_before_an_outcome_is_chosen(repo):
    counts = repo.attrition_counts(study(outcome=None, person_filters={"gender": ["F"]}))
    assert counts[-1] == {"step": "gender: F", "treated": 1, "control": 1}


@pytest.mark.parametrize("feature", [
    ed("ed_5y_pre", -5, -1, unit="years"),                    # look-back starts mid 2016
    ed("ed_5y_post", 1, 5, unit="years", role="outcome"),     # follow-up ends mid 2026
])
def test_windows_outside_the_data_coverage_exclude_the_patient(repo, feature):
    s = study(feature, outcome=None) if feature["role"] == "outcome" else study(feature)
    last = repo.attrition_counts(s)[-1]
    assert last == {"step": "Data covers every look-back and follow-up window",
                    "treated": 0, "control": 0}


def test_exclusion_criterion(repo):
    s = study(dx("no_asthma", "asthma", role="inclusion", keep_if={"op": "==", "value": 0}))
    assert list(repo.analysis_table(s)["patient_id"]) == ["T1", "T2", "C2"]


# ------------------------------------------------------------------ preview

def test_feature_preview_summarises_by_group(repo):
    summary = repo.feature_preview(FeatureSpec.model_validate(ed("ed_pre", -365, -1)), study())
    assert summary["feature"] == "ed_pre"
    column = summary["columns"][0]
    assert column["column"] == "ed_pre"
    assert column["treated"] == {"n": 2, "nonzero": 1, "mean": 1.0, "min": 0.0, "max": 2.0}
    assert column["control"] == {"n": 2, "nonzero": 2, "mean": 2.0, "min": 1.0, "max": 3.0}
    # Two patients per group is below the suppression threshold of 5.
    codes = [i["code"] for i in summary["issues"]]
    assert "small_cell" in codes


def test_previewing_an_inclusion_criterion_does_not_apply_it(repo):
    criterion = FeatureSpec.model_validate(
        dx("has_diabetes", "diabetes", role="inclusion", keep_if={"op": "==", "value": 1}))
    summary = repo.feature_preview(criterion, study(outcome=None))
    column = summary["columns"][0]
    assert column["treated"]["n"] == 2
    assert column["treated"]["nonzero"] == 1


def test_preview_replaces_a_feature_of_the_same_name(repo):
    s = study(ed("ed_pre", -365, -1))
    edited = FeatureSpec.model_validate(ed("ed_pre", -30, -1))
    summary = repo.feature_preview(edited, s)
    # Within 30 days of index: T1 day -1, C1 days -15 and -14.
    assert summary["columns"][0]["treated"]["max"] == 1.0
    assert summary["columns"][0]["control"]["max"] == 2.0


def test_preview_warns_about_a_constant_feature(repo):
    summary = repo.feature_preview(FeatureSpec.model_validate(
        ed("p1_pre", -365, -1, filters={"triage_level": ["P1"]})), study())
    assert "constant_feature" in [i["code"] for i in summary["issues"]]


# ------------------------------------------------------- refusing bad input

def test_study_with_design_errors_is_refused(repo):
    with pytest.raises(StudyError) as raised:
        repo.analysis_table(study(ed("ed_lookahead", -365, 0)))
    assert "covariate_lookahead" in [i["code"] for i in raised.value.issues]


def test_injection_through_a_filter_value_never_reaches_sql(repo):
    queries = []
    real_run = repo.run

    def spy(query: str, params: dict) -> pd.DataFrame:
        queries.append((query, params))
        return real_run(query, params)

    repo.run = spy
    attack = "SCDF') OR 1=1 --"
    with pytest.raises(StudyError) as raised:
        repo.analysis_table(study(ed("x", -365, -1, filters={"mode_of_arrival": [attack]})))
    assert "unknown_dimension_value" in [i["code"] for i in raised.value.issues]
    # Only the lookup of allowed values ran, and the attack text appears nowhere.
    assert len(queries) == 1
    assert "DISTINCT" in queries[0][0]
    assert attack not in queries[0][0]


def test_dimension_values_are_discovered_and_cached(repo):
    calls = []
    real_run = repo.run

    def counting(query: str, params: dict) -> pd.DataFrame:
        calls.append(query)
        return real_run(query, params)

    repo.run = counting
    assert repo.dimension_values("ed_episodes", "mode_of_arrival") == ["Own transport", "SCDF"]
    assert repo.dimension_values("ed_episodes", "mode_of_arrival") == ["Own transport", "SCDF"]
    assert repo.dimension_values("condition", "condition_name") == ["asthma", "copd", "diabetes"]
    assert repo.dimension_values("person", "ethnicity") == ["Chinese", "Indian", "Malay"]
    assert len(calls) == 3


def test_pinned_dimension_values_need_no_query(repo):
    repo.mapping.sources[0].dimensions["triage_level"].values = ["P1", "P2"]
    repo.run = None   # any query would fail
    assert repo.dimension_values("ed_episodes", "triage_level") == ["P1", "P2"]


@pytest.mark.parametrize("source, dimension", [
    ("ed_episodes", "patient_id"),
    ("ed_episodes; DROP TABLE x", "mode_of_arrival"),
    ("person", "date_of_birth"),
    ("pharmacy", "drug"),
])
def test_dimension_values_refuse_names_not_in_the_mapping(repo, source, dimension):
    with pytest.raises(LookupError):
        repo.dimension_values(source, dimension)
