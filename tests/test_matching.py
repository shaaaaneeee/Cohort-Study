"""Tests for the covariate matrix, propensity scores, matching and balance, on small hand-made inputs."""
import numpy as np
import pandas as pd
import pytest

from cohort_studio.features import StudySpec
from cohort_studio.matching import balance, covariate_matrix, match_pairs, propensity_scores
from cohort_studio.models import AnalysisError


def study(person_covariates: list[str], feature_names: list[str]) -> StudySpec:
    features = []
    for name in feature_names:
        features.append({"name": name, "label": name, "source": "ed_episodes",
                         "window": {"from": -365, "to": -1, "unit": "days"},
                         "aggregation": "count", "role": "covariate"})
    return StudySpec.model_validate({"exposure": "program_a", "person_covariates": person_covariates,
                                     "features": features})


def probabilities(logits: list[float]) -> np.ndarray:
    return 1 / (1 + np.exp(-np.array(logits)))


def test_categories_become_dummies_with_the_largest_group_as_reference():
    table = pd.DataFrame({"age": [50, 60, 70, 80], "gender": ["F", "F", "M", None],
                          "ed_pre": [0, 1, 2, 3]})
    X, issues = covariate_matrix(table, study(["age", "gender"], ["ed_pre"]))
    assert list(X.columns) == ["age", "gender=M", "gender=Missing", "ed_pre"]
    assert list(X["gender=M"]) == [0, 0, 1, 0]
    assert list(X["gender=Missing"]) == [0, 0, 0, 1]
    assert issues == []


def test_constant_covariate_is_dropped_with_a_warning():
    table = pd.DataFrame({"age": [50, 60, 70, 80], "ed_pre": [0, 0, 0, 0]})
    X, issues = covariate_matrix(table, study(["age"], ["ed_pre"]))
    assert list(X.columns) == ["age"]
    assert [i["code"] for i in issues] == ["constant_feature"]


def test_periodised_covariate_gives_one_column_per_period():
    spec = StudySpec.model_validate({"exposure": "program_a", "features": [
        {"name": "ed_q", "label": "q", "source": "ed_episodes",
         "window": {"from": -6, "to": -1, "unit": "months"}, "aggregation": "count",
         "periodise": {"grain": "quarter", "n": 2}, "role": "covariate"}]})
    table = pd.DataFrame({"ed_q_p1": [0, 1, 2], "ed_q_p2": [1, 0, 3]})
    X, _ = covariate_matrix(table, spec)
    assert list(X.columns) == ["ed_q_p1", "ed_q_p2"]


def test_nearest_control_within_the_caliper_is_chosen():
    #             treated     controls
    logits = [0.0, 1.0, 0.05, 0.9, 5.0]
    exposure = np.array([1, 1, 0, 0, 0])
    pairs = match_pairs(probabilities(logits), exposure, seed=0)
    assert sorted(pairs) == [(0, 2), (1, 3)]


def test_a_control_is_used_only_once():
    logits = [0.0, 0.02, 0.01, 3.0]
    exposure = np.array([1, 1, 0, 0])
    pairs = match_pairs(probabilities(logits), exposure, seed=0)
    # Both treated want control 2; the other control is far outside the caliper.
    assert len(pairs) == 1
    assert pairs[0][1] == 2


def test_treated_with_no_close_control_stay_unmatched():
    logits = [4.0, 0.0, 0.1, -0.1, 0.05]
    exposure = np.array([1, 1, 0, 0, 0])
    pairs = match_pairs(probabilities(logits), exposure, seed=0)
    assert [t for t, _ in pairs] == [1]


def test_matching_is_repeatable_for_a_seed():
    rng = np.random.default_rng(1)
    scores = rng.random(200)
    exposure = (rng.random(200) < 0.3).astype(int)
    assert match_pairs(scores, exposure, seed=4) == match_pairs(scores, exposure, seed=4)


def test_balance_uses_the_pre_matching_spread_for_both_smds():
    X = pd.DataFrame({"x": [1.0, 3.0, 0.0, 2.0, 10.0]})
    exposure = np.array([1, 1, 0, 0, 0])
    matched = np.array([True, True, True, True, False])
    row = balance(X, exposure, matched)[0]
    sd = np.sqrt((np.var([1, 3], ddof=1) + np.var([0, 2, 10], ddof=1)) / 2)
    assert row["smd_before"] == pytest.approx((2 - 4) / sd)
    assert row["smd_after"] == pytest.approx((2 - 1) / sd)
    assert row["control_mean_after"] == 1.0


def test_propensity_rises_with_a_covariate_that_predicts_treatment():
    rng = np.random.default_rng(2)
    x = rng.normal(size=2000)
    exposure = (rng.random(2000) < 1 / (1 + np.exp(-(x - 1)))).astype(int)
    scores = propensity_scores(pd.DataFrame({"x": x}), exposure)
    assert np.corrcoef(x, scores)[0, 1] > 0.9


def test_a_covariate_that_separates_the_groups_is_refused():
    exposure = np.array([1, 1, 1, 0, 0, 0])
    X = pd.DataFrame({"only_treated_have_it": exposure.astype(float), "age": [5, 6, 7, 5, 6, 8.0]})
    with pytest.raises(AnalysisError, match="separate"):
        propensity_scores(X, exposure)
