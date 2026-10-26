"""Tests for the synthetic data and for the analysis table built from it.

The analysis table is checked against an independent calculation in pandas
straight from the generated tables, for every patient and every feature.
"""
import numpy as np
import pandas as pd
import pytest

from cohort_studio import synthetic
from cohort_studio.features import StudySpec
from cohort_studio.mapping import load_mapping
from tests.support import repository_for

FEATURES = [
    {"name": "ed_pre", "label": "ED attendances, 12 months before", "source": "ed_episodes",
     "window": {"from": -365, "to": -1, "unit": "days"}, "aggregation": "count", "role": "covariate"},
    {"name": "scdf_pre", "label": "Any SCDF attendance, 12 months before", "source": "ed_episodes",
     "filters": {"mode_of_arrival": ["SCDF"]},
     "window": {"from": -365, "to": -1, "unit": "days"}, "aggregation": "binary", "role": "covariate"},
    {"name": "los_mean_pre", "label": "Mean LOS, 12 months before", "source": "ed_episodes",
     "window": {"from": -365, "to": -1, "unit": "days"}, "aggregation": "mean",
     "measure": "los_hours", "role": "covariate"},
    {"name": "ed_q", "label": "ED attendances by quarter, 2 years before", "source": "ed_episodes",
     "window": {"from": -24, "to": -1, "unit": "months"}, "aggregation": "count",
     "periodise": {"grain": "quarter", "n": 8}, "role": "covariate"},
    {"name": "dx_copd", "label": "COPD before the index year", "source": "condition",
     "filters": {"condition_name": ["copd"]},
     "window": {"from": -50, "to": -1, "unit": "years"}, "aggregation": "binary", "role": "covariate"},
    {"name": "ed_post", "label": "ED attendances, 12 months after", "source": "ed_episodes",
     "window": {"from": 1, "to": 365, "unit": "days"}, "aggregation": "count", "role": "outcome"},
]


def make_study(seed: int = 0) -> StudySpec:
    return StudySpec.model_validate({"exposure": "program_a", "seed": seed, "features": FEATURES})


@pytest.fixture(scope="module")
def analysis(synthetic_db, config_path):
    return repository_for(synthetic_db, load_mapping(config_path)).analysis_table(make_study())


# --------------------------------------------------------- the data itself

def test_generation_is_repeatable():
    a = synthetic.generate(patients=300, seed=5)
    b = synthetic.generate(patients=300, seed=5)
    for table in a:
        pd.testing.assert_frame_equal(a[table], b[table])


def test_selection_bias_is_planted(synthetic_tables):
    patients = synthetic_tables["master_patient"]
    members = set(synthetic_tables["program_members"]["patient_id"])
    enrolled = patients["patient_id"].isin(members)
    assert patients.loc[enrolled, "date_of_birth"].mean() < patients.loc[~enrolled, "date_of_birth"].mean()

    conditions = synthetic_tables["chronic_conditions"]
    for condition in ["diabetes", "copd", "heart_failure", "ckd"]:
        has = set(conditions.loc[conditions["condition_name"] == condition, "patient_id"])
        share_enrolled = len(has & members) / len(members)
        share_not = len(has - members) / (len(patients) - len(members))
        assert share_enrolled > 1.5 * share_not, condition


def test_planted_effect_shows_within_members(synthetic_tables):
    # Each member's own rate before and after enrolment. Comparing a member
    # with themselves removes the selection bias, so the ratio should be
    # close to the planted rate ratio.
    members = synthetic_tables["program_members"].set_index("patient_id")["enrollment_date"]
    ed = synthetic_tables["ed_episodes"]
    ed = ed[ed["patient_id"].isin(members.index)]
    enrolled_on = ed["patient_id"].map(members)
    events_after = (ed["attendance_date"] > enrolled_on).sum()
    events_before = (ed["attendance_date"] <= enrolled_on).sum()
    start = pd.Timestamp(synthetic.DATA_START)
    end = pd.Timestamp(synthetic.DATA_END)
    years_before = ((members - start).dt.days + 1).sum() / 365.25
    years_after = ((end - members).dt.days).sum() / 365.25
    ratio = (events_after / years_after) / (events_before / years_before)
    assert ratio == pytest.approx(synthetic.RATE_RATIO, abs=0.1)


def test_counts_are_overdispersed(synthetic_tables):
    counts = synthetic_tables["ed_episodes"].groupby("patient_id").size()
    counts = counts.reindex(synthetic_tables["master_patient"]["patient_id"], fill_value=0)
    assert counts.var() > 1.5 * counts.mean()


def test_without_frailty_counts_are_close_to_poisson():
    tables = synthetic.generate(patients=3000, seed=3, frailty_variance=0)
    ed = tables["ed_episodes"]
    # Same age and conditions, so the only spread left is Poisson noise:
    # compare patients who have no conditions and similar ages.
    patients = tables["master_patient"]
    healthy = set(patients["patient_id"]) - set(tables["chronic_conditions"]["patient_id"])
    born = patients.set_index("patient_id")["date_of_birth"]
    band = [p for p in healthy if pd.Timestamp("1955-01-01") <= born[p] < pd.Timestamp("1965-01-01")]
    counts = ed.groupby("patient_id").size().reindex(band, fill_value=0)
    assert counts.var() / counts.mean() == pytest.approx(1.0, abs=0.25)


# ------------------------------------------------------------- the cohort

def test_treated_are_indexed_at_enrolment(analysis, synthetic_tables):
    enrolment = synthetic_tables["program_members"].set_index("patient_id")["enrollment_date"]
    treated = analysis[analysis["exposure"] == 1].set_index("patient_id")
    assert set(treated.index) == set(enrolment.index)
    assert (treated["index_date"] == enrolment.reindex(treated.index)).all()


def test_controls_draw_their_index_dates_from_the_treated(analysis, synthetic_tables):
    treated_dates = set(synthetic_tables["program_members"]["enrollment_date"])
    controls = analysis[analysis["exposure"] == 0]
    members = set(synthetic_tables["program_members"]["patient_id"])
    assert len(controls) == len(synthetic_tables["master_patient"]) - len(members)
    assert set(controls["index_date"]) <= treated_dates
    # Same distribution: the quartiles agree to within a few weeks.
    origin = pd.Timestamp("2020-01-01")
    treated_days = (analysis.loc[analysis["exposure"] == 1, "index_date"] - origin).dt.days
    control_days = (controls["index_date"] - origin).dt.days
    for q in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert abs(control_days.quantile(q) - treated_days.quantile(q)) < 45, q


def test_control_index_dates_depend_on_the_seed(synthetic_repo, analysis):
    again = synthetic_repo.analysis_table(make_study(seed=0))
    pd.testing.assert_frame_equal(again, analysis)
    other = synthetic_repo.analysis_table(make_study(seed=1)).set_index("patient_id")["index_date"]
    controls = analysis[analysis["exposure"] == 0].set_index("patient_id")["index_date"]
    changed = (other.reindex(controls.index) != controls).mean()
    assert changed > 0.9


def test_crude_comparison_is_biased(analysis):
    # The programme lowers ED use, yet treated patients attend more because
    # they were sicker to begin with. This is what Phase 3 has to undo.
    means = analysis.groupby("exposure")["ed_post"].mean()
    assert means[1] / means[0] > 1.0


# -------------------------------------------- independent recalculation

def expected_features(analysis: pd.DataFrame, tables: dict) -> pd.DataFrame:
    """The FEATURES, computed in pandas without any of the SQL code."""
    cohort = analysis[["patient_id", "index_date", "age"]].copy()
    ed = tables["ed_episodes"].merge(cohort[["patient_id", "index_date"]], on="patient_id")
    day = (ed["attendance_date"] - ed["index_date"]).dt.days
    pre = ed[(day >= -365) & (day <= -1)]
    post = ed[(day >= 1) & (day <= 365)]

    result = cohort.set_index("patient_id")
    result["ed_pre"] = pre.groupby("patient_id").size()
    result["scdf_pre"] = (pre["mode_of_arrival"] == "SCDF").groupby(pre["patient_id"]).max().astype(int)
    result["los_mean_pre"] = pre.groupby("patient_id")["los_hours"].mean()
    result["ed_post"] = post.groupby("patient_id").size()
    for k in range(1, 9):
        low = ed["index_date"] + pd.DateOffset(months=-24 + 3 * (k - 1))
        high = ed["index_date"] + pd.DateOffset(months=-24 + 3 * k)
        in_period = ed[(ed["attendance_date"] >= low) & (ed["attendance_date"] < high)]
        result[f"ed_q_p{k}"] = in_period.groupby("patient_id").size()

    conditions = tables["chronic_conditions"]
    copd = conditions[conditions["condition_name"] == "copd"].merge(
        cohort[["patient_id", "index_date"]], on="patient_id")
    before = copd[copd["diagnosis_year"] <= copd["index_date"].dt.year - 1]
    result["dx_copd"] = before.groupby("patient_id").size().clip(upper=1)

    born = tables["master_patient"].set_index("patient_id")["date_of_birth"].reindex(result.index)
    index = result["index_date"]
    birthday_to_come = (index.dt.month < born.dt.month) | (
        (index.dt.month == born.dt.month) & (index.dt.day < born.dt.day))
    result["expected_age"] = index.dt.year - born.dt.year - birthday_to_come.astype(int)
    return result.fillna(0).reset_index()


def test_analysis_table_matches_an_independent_calculation(analysis, synthetic_tables):
    expected = expected_features(analysis, synthetic_tables)
    columns = ["ed_pre", "scdf_pre", "los_mean_pre", "ed_post", "dx_copd"]
    for k in range(1, 9):
        columns.append(f"ed_q_p{k}")
    for column in columns:
        np.testing.assert_allclose(analysis[column].to_numpy(dtype=float),
                                   expected[column].to_numpy(dtype=float),
                                   rtol=1e-9, err_msg=column)
    assert (analysis["age"].to_numpy() == expected["expected_age"].to_numpy()).all()
    # The check would prove little if the features were mostly zero.
    assert analysis["ed_pre"].sum() > 1000
    assert analysis["dx_copd"].sum() > 100
