"""End-to-end tests: synthetic data -> database -> analysis table -> statistics.

The synthetic data has a planted rate ratio of 0.70 and a selection bias that
makes the crude comparison point the wrong way. These tests check that the
full pipeline removes the bias and recovers the planted effect, and that it
finds nothing when nothing was planted.

An estimate passes if it is within three standard errors of the truth.
"""
import numpy as np
import pandas as pd
import pytest

from cohort_studio import synthetic
from cohort_studio.analysis import run_analysis
from cohort_studio.features import StudySpec
from cohort_studio.models import AnalysisError
from tests.support import build_database, repository_for

Z95 = 1.959964
CONDITIONS = ["diabetes", "hypertension", "copd", "heart_failure", "ckd", "depression", "asthma"]


@pytest.fixture(scope="module")
def databases(tmp_path_factory) -> dict:
    """20,000 patients each: the default data, more overdispersed data, data
    without frailty, and data with no programme effect at all."""
    settings = {"default": {}, "overdispersed": {"frailty_variance": 2.0},
                "no_frailty": {"frailty_variance": 0.0}, "no_effect": {"rate_ratio": 1.0}}
    folder = tmp_path_factory.mktemp("analysis")
    paths = {}
    for name, kwargs in settings.items():
        paths[name] = folder / f"{name}.duckdb"
        build_database(paths[name], synthetic.generate(patients=20000, seed=7, **kwargs))
    return paths


def make_study(**outcome_overrides) -> StudySpec:
    features = []
    for condition in CONDITIONS:
        features.append({"name": f"dx_{condition}", "label": f"{condition} before the index year",
                         "source": "condition", "filters": {"condition_name": [condition]},
                         "window": {"from": -50, "to": -1, "unit": "years"},
                         "aggregation": "binary", "role": "covariate"})
    features.append({"name": "ed_pre", "label": "ED attendances, 12 months before",
                     "source": "ed_episodes", "window": {"from": -365, "to": -1, "unit": "days"},
                     "aggregation": "count", "role": "covariate"})
    outcome = {"name": "ed_post", "label": "ED attendances, 12 months after",
               "source": "ed_episodes", "window": {"from": 1, "to": 12, "unit": "months"},
               "aggregation": "count", "role": "outcome"}
    outcome.update(outcome_overrides)
    features.append(outcome)
    return StudySpec.model_validate({"exposure": "program_a", "person_covariates": ["age", "gender"],
                                     "features": features})


def analyse(databases, name: str, spec: StudySpec, mapping) -> tuple[dict, pd.DataFrame]:
    table = repository_for(databases[name], mapping).analysis_table(spec)
    return run_analysis(table, spec), table


def assert_close_to(model: dict, truth: float):
    se = (np.log(model["ci_high"]) - np.log(model["ci_low"])) / (2 * Z95)
    distance = abs(np.log(model["estimate"]) - np.log(truth)) / se
    assert distance < 3, f"estimate {model['estimate']:.3f} is {distance:.1f} SE from {truth}"


def crude_ratio(table: pd.DataFrame, column: str) -> float:
    means = table.groupby("exposure")[column].mean()
    return means[1] / means[0]


# --------------------------------------------------- recovering the effect

def test_count_outcome_recovers_the_planted_rate_ratio(databases, mapping):
    result, table = analyse(databases, "default", make_study(), mapping)
    # Before adjustment the programme looks harmful.
    assert crude_ratio(table, "ed_post") > 1.3
    assert result["model"]["model"] == "poisson"
    assert_close_to(result["model"], synthetic.RATE_RATIO)
    assert "Rate ratio" in result["interpretation"]


def test_matching_balances_the_covariates(databases, mapping):
    result, _ = analyse(databases, "default", make_study(), mapping)
    before = {}
    for row in result["balance"]:
        before[row["covariate"]] = row["smd_before"]
        assert abs(row["smd_after"]) < 0.1, row["covariate"]
    # The planted selection: members are older and sicker.
    assert before["age"] > 0.5
    assert before["dx_copd"] > 0.3
    assert result["cohort"]["treated_matched"] > 0.95 * result["cohort"]["treated"]
    assert "imbalance" not in [i["code"] for i in result["issues"]]


def test_overdispersed_counts_switch_to_negative_binomial(databases, mapping):
    spec = make_study(window={"from": 1, "to": 24, "unit": "months"})
    result, _ = analyse(databases, "overdispersed", spec, mapping)
    assert result["model"]["model"] == "negative_binomial"
    assert_close_to(result["model"], synthetic.RATE_RATIO)


def test_time_to_first_event_recovers_the_hazard_ratio(databases, mapping):
    # Without frailty every patient's hazard is constant, so the hazard ratio
    # equals the planted rate ratio. With frailty the population hazard ratio
    # drifts towards 1 over follow-up as the frailest controls have their
    # first event early, so the comparison would not be exact.
    result, _ = analyse(databases, "no_frailty", make_study(aggregation="time_to_first"), mapping)
    assert result["model"]["measure"] == "Hazard ratio"
    assert_close_to(result["model"], synthetic.RATE_RATIO)


def test_periodised_outcome_uses_gee_and_recovers_the_rate_ratio(databases, mapping):
    spec = make_study(window={"from": 1, "to": 24, "unit": "months"},
                      periodise={"grain": "quarter", "n": 8})
    result, _ = analyse(databases, "default", spec, mapping)
    assert result["model"]["model"] == "gee"
    assert_close_to(result["model"], synthetic.RATE_RATIO)


def test_binary_outcome_shows_a_reduction(databases, mapping):
    # The odds ratio for "any attendance" is not the planted rate ratio (see
    # models.py on odds ratios), so only its direction is checked here; the
    # no-effect data below checks it lands on 1 when it should.
    result, _ = analyse(databases, "default", make_study(aggregation="binary"), mapping)
    assert result["model"]["measure"] == "Odds ratio"
    assert result["model"]["ci_high"] < 1


@pytest.mark.parametrize("aggregation", ["count", "binary"])
def test_no_effect_is_found_where_none_was_planted(databases, mapping, aggregation):
    result, table = analyse(databases, "no_effect", make_study(aggregation=aggregation), mapping)
    assert crude_ratio(table, "ed_post") > 1.3
    assert_close_to(result["model"], 1.0)


# ------------------------------------------------------------- warnings

def small_table(n: int = 60, seed: int = 0) -> tuple[pd.DataFrame, StudySpec]:
    """An in-memory analysis table, no database needed."""
    rng = np.random.default_rng(seed)
    table = pd.DataFrame({
        "patient_id": [f"P{i}" for i in range(n)],
        "exposure": np.repeat([1, 0], n // 2),
        "age": rng.integers(40, 80, n).astype(float),
        "dx_copd": (rng.random(n) < 0.3).astype(int),
        "person_years": 1.0,
    })
    table["ed_post"] = 0
    table.loc[[0, 1, 2], "ed_post"] = 1          # three treated with the outcome
    table.loc[[30, 31, 32, 33, 34, 35], "ed_post"] = 2
    spec = StudySpec.model_validate({"exposure": "program_a", "person_covariates": ["age"], "features": [
        {"name": "dx_copd", "label": "COPD", "source": "condition",
         "filters": {"condition_name": ["copd"]}, "window": {"from": -50, "to": -1, "unit": "years"},
         "aggregation": "binary", "role": "covariate"},
        {"name": "ed_post", "label": "ED attendances", "source": "ed_episodes",
         "window": {"from": 1, "to": 12, "unit": "months"}, "aggregation": "count", "role": "outcome"}]})
    return table, spec


def codes(result: dict) -> list[str]:
    return [i["code"] for i in result["issues"]]


def test_small_cohort_warns_about_events_per_coefficient_and_small_cells():
    table, spec = small_table()
    result = run_analysis(table, spec)
    assert "low_events_per_covariate" in codes(result)
    assert "small_cell" in codes(result)


def test_without_covariates_the_comparison_is_unadjusted_and_says_so():
    table, spec = small_table()
    spec = spec.model_copy(update={"person_covariates": [], "features": spec.features[1:]})
    result = run_analysis(table, spec)
    assert "no_covariates" in codes(result)
    assert result["cohort"]["matched"] is False
    assert result["cohort"]["treated_matched"] == 30


def test_patients_with_missing_covariates_are_left_out_with_a_warning():
    table, spec = small_table()
    table.loc[5, "age"] = np.nan
    result = run_analysis(table, spec)
    assert "missing_covariates" in codes(result)
    assert result["cohort"]["treated"] == 29


def test_a_cohort_with_only_one_group_is_refused():
    table, spec = small_table()
    with pytest.raises(AnalysisError, match="both groups"):
        run_analysis(table[table["exposure"] == 1], spec)


# ---------------------------------------------------------- data for plots

def test_plot_data_for_a_count_outcome(databases, mapping):
    result, _ = analyse(databases, "default", make_study(), mapping)
    plots = result["plots"]
    assert plots["survival"] is None and plots["periods"] is None
    propensity = plots["propensity"]
    assert len(propensity["edges"]) == 21
    for stage in ("before", "after"):
        for group in ("treated", "control"):
            assert sum(propensity[stage][group]) == pytest.approx(1.0)
    # Matching makes the control distribution look like the treated one.
    def gap(stage):
        return sum(abs(t - c) for t, c in zip(propensity[stage]["treated"], propensity[stage]["control"]))
    assert gap("after") < gap("before") / 3


def test_plot_data_for_time_to_event_and_periodised_outcomes(databases, mapping):
    result, _ = analyse(databases, "default", make_study(aggregation="time_to_first"), mapping)
    survival = result["plots"]["survival"]
    for group in ("treated", "control"):
        curve = survival[group]
        assert curve[0] == 1.0
        assert all(later <= earlier for earlier, later in zip(curve, curve[1:]))
    # The programme lowers the hazard, so members stay event-free longer.
    assert survival["treated"][-1] > survival["control"][-1]

    spec = make_study(window={"from": 1, "to": 24, "unit": "months"},
                      periodise={"grain": "quarter", "n": 8})
    periods = analyse(databases, "default", spec, mapping)[0]["plots"]["periods"]
    assert len(periods["treated"]) == 8
    assert sum(periods["treated"]) < sum(periods["control"])
