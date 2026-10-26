"""Tests for model selection and fitting, on data simulated here with a known effect.

An estimate passes if it is within three standard errors of the true value.
A check against the 95% interval would fail by chance one run in twenty.
"""
import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from cohort_studio.features import FeatureSpec
from cohort_studio.models import fit_outcome, implied_model

Z95 = 1.959964


def outcome(**overrides) -> FeatureSpec:
    spec = {"name": "y", "label": "ED attendances", "source": "ed_episodes",
            "window": {"from": 1, "to": 12, "unit": "months"}, "aggregation": "count",
            "role": "outcome"}
    spec.update(overrides)
    return FeatureSpec.model_validate(spec)


def assert_close_to(result: dict, truth: float):
    se = (np.log(result["ci_high"]) - np.log(result["ci_low"])) / (2 * Z95)
    distance = abs(np.log(result["estimate"]) - np.log(truth)) / se
    assert distance < 3, f"estimate {result['estimate']:.3f} is {distance:.1f} SE from {truth}"


def patients(n: int, seed: int) -> tuple[pd.DataFrame, np.random.Generator]:
    rng = np.random.default_rng(seed)
    data = pd.DataFrame({"exposure": rng.integers(0, 2, n), "x": rng.normal(size=n),
                         "person_years": 1.0})
    return data, rng


# --------------------------------------------------------------- selection

@pytest.mark.parametrize("overrides, model, measure", [
    ({"aggregation": "binary"}, "logistic", "Odds ratio"),
    ({"aggregation": "count"}, "count", "Rate ratio"),
    ({"aggregation": "distinct_count"}, "count", "Rate ratio"),
    ({"aggregation": "rate"}, "count", "Rate ratio"),
    ({"aggregation": "time_to_first"}, "cox", "Hazard ratio"),
    ({"window": {"from": 1, "to": 24, "unit": "months"}, "periodise": {"grain": "quarter", "n": 8}},
     "gee", "Rate ratio"),
])
def test_the_model_is_known_before_any_data(overrides, model, measure):
    implied = implied_model(outcome(**overrides))
    assert implied["model"] == model
    assert implied["measure"] == measure
    assert implied["reason"]


def test_periodised_model_explains_why():
    implied = implied_model(outcome(window={"from": 1, "to": 24, "unit": "months"},
                                    periodise={"grain": "quarter", "n": 8}))
    assert "8 periods" in implied["reason"]
    assert "correlated" in implied["reason"]


# ------------------------------------------------------------------ counts

def test_poisson_counts_get_a_poisson_model():
    data, rng = patients(4000, seed=1)
    data["y"] = rng.poisson(np.exp(0.3 + np.log(0.7) * data["exposure"] + 0.4 * data["x"]))
    result = fit_outcome(data, outcome(), ["x"], np.arange(len(data)))
    assert result["model"] == "poisson"
    assert result["dispersion"] == pytest.approx(1.0, abs=0.15)
    assert_close_to(result, 0.7)


def test_overdispersed_counts_get_a_negative_binomial_model():
    data, rng = patients(4000, seed=2)
    frailty = rng.gamma(1.0, 1.0, len(data))     # variance 1
    data["y"] = rng.poisson(np.exp(0.7 + np.log(0.7) * data["exposure"] + 0.4 * data["x"]) * frailty)
    result = fit_outcome(data, outcome(), ["x"], np.arange(len(data)))
    assert result["model"] == "negative_binomial"
    assert result["dispersion"] > 1.5
    assert_close_to(result, 0.7)


def test_a_rate_outcome_gives_the_same_answer_as_its_counts():
    data, rng = patients(2000, seed=3)
    data["person_years"] = 2.0
    counts = rng.poisson(2.0 * np.exp(0.1 + np.log(0.7) * data["exposure"]))
    groups = np.arange(len(data))
    from_counts = fit_outcome(data.assign(y=counts), outcome(), ["x"], groups)
    from_rates = fit_outcome(data.assign(y=counts / 2.0), outcome(aggregation="rate"), ["x"], groups)
    assert from_rates["estimate"] == pytest.approx(from_counts["estimate"])


# ------------------------------------------------------------- yes and no

def test_logistic_regression_recovers_the_odds_ratio():
    data, rng = patients(6000, seed=4)
    log_odds = -0.5 + np.log(0.5) * data["exposure"] + 0.8 * data["x"]
    data["y"] = (rng.random(len(data)) < 1 / (1 + np.exp(-log_odds))).astype(int)
    result = fit_outcome(data, outcome(aggregation="binary"), ["x"], np.arange(len(data)))
    assert result["measure"] == "Odds ratio"
    assert_close_to(result, 0.5)


# ----------------------------------------------------------- time to event

def survival(n: int, seed: int, hazard_ratio_early: float, hazard_ratio_late: float) -> pd.DataFrame:
    """Exponential times censored at 365 days; the hazard ratio may change at day 120."""
    data, rng = patients(n, seed)
    base = 1 / 400 * np.exp(0.5 * data["x"])
    early = np.where(data["exposure"] == 1, hazard_ratio_early, 1.0) * base
    late = np.where(data["exposure"] == 1, hazard_ratio_late, 1.0) * base
    first = rng.exponential(1 / early)
    second = 120 + rng.exponential(1 / late)
    time = np.where(first < 120, first, second)
    data["y_event"] = (time <= 365).astype(int)
    data["y_days"] = np.ceil(np.minimum(time, 365))
    return data


def test_cox_recovers_the_hazard_ratio():
    data = survival(4000, seed=5, hazard_ratio_early=0.6, hazard_ratio_late=0.6)
    result = fit_outcome(data, outcome(aggregation="time_to_first"), ["x"], np.arange(len(data)))
    assert result["measure"] == "Hazard ratio"
    assert_close_to(result, 0.6)


def test_a_hazard_ratio_that_changes_over_time_is_flagged():
    data = survival(4000, seed=6, hazard_ratio_early=0.2, hazard_ratio_late=2.0)
    result = fit_outcome(data, outcome(aggregation="time_to_first"), ["x"], np.arange(len(data)))
    assert "proportional_hazards" in [i["code"] for i in result["issues"]]


# ------------------------------------------------------- repeated measures

def panel(n: int, seed: int) -> tuple[pd.DataFrame, FeatureSpec]:
    """Eight quarterly counts per patient, sharing a patient-level rate."""
    data, rng = patients(n, seed)
    data["person_years"] = 2.0
    frailty = rng.gamma(1.0, 1.0, n)
    rate = np.exp(-0.5 + np.log(0.7) * data["exposure"] + 0.4 * data["x"]) * frailty
    for k in range(1, 9):
        data[f"y_p{k}"] = rng.poisson(rate)
    spec = outcome(window={"from": 1, "to": 24, "unit": "months"},
                   periodise={"grain": "quarter", "n": 8})
    return data, spec


def test_gee_recovers_the_rate_ratio_from_repeated_measures():
    data, spec = panel(2000, seed=7)
    result = fit_outcome(data, spec, ["x"], np.arange(len(data)))
    assert result["name"].startswith("GEE")
    assert_close_to(result, 0.7)
    # Exposure, x and seven period effects.
    assert result["parameters"] == 9


def test_treating_repeated_measures_as_independent_understates_uncertainty():
    # Why the periodised case needs GEE: the same data fitted as if every
    # patient-period were a separate patient gives a far narrower interval.
    data, spec = panel(2000, seed=8)
    gee = fit_outcome(data, spec, ["x"], np.arange(len(data)))
    long = pd.concat([data[["exposure", "x"]].assign(y=data[f"y_p{k}"]) for k in range(1, 9)])
    naive = sm.GLM(long["y"], sm.add_constant(long[["exposure", "x"]]),
                   family=sm.families.Poisson()).fit()
    gee_width = np.log(gee["ci_high"]) - np.log(gee["ci_low"])
    naive_low, naive_high = naive.conf_int().loc["exposure"]
    assert gee_width > 1.5 * (naive_high - naive_low)
