"""Balance the treated and control groups by propensity score matching.

covariate_matrix() turns the analysis-ready table into the numeric
covariates the models use. propensity_scores() estimates each patient's
probability of being treated from those covariates, match_pairs() pairs each
treated patient with the control closest to them on that probability, and
balance() reports how alike the groups were before and after.

Matching keeps every treated patient who has a close enough control, so the
estimate is the average effect in the treated (ATT): the effect of the
programme on the kind of patient who joins it.
"""
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import PerfectSeparationWarning

from cohort_studio.features import StudySpec, feature_columns
from cohort_studio.models import AnalysisError
from cohort_studio.validator import check_feature_variation

# Austin (2011): a caliper of 0.2 standard deviations of the logit of the
# propensity score removes most of the bias matching can remove while still
# finding a partner for most treated patients.
CALIPER_SD = 0.2

# A standardised mean difference under 0.1 is the usual sign that a
# covariate is adequately balanced (Austin, 2009; Normand et al., 2001).
SMD_LIMIT = 0.1


def covariate_matrix(table: pd.DataFrame, spec: StudySpec) -> tuple[pd.DataFrame, list[dict]]:
    """The study's covariates as numeric columns, one row per patient, and any warnings.

    Age and every covariate feature column are used as they are. A person
    attribute such as ethnicity becomes one 0/1 column per category except
    the most common, which is the reference; the largest group as reference
    gives the most stable estimates for the others. A missing value is its
    own category ("Missing") so the patient is kept.

    A column with the same value for everyone is dropped: it carries no
    information and would make the propensity model impossible to fit.
    """
    columns = {}
    for name in spec.person_covariates:
        if name == "age":
            columns["age"] = table["age"].astype(float)
            continue
        values = table[name].astype("string").fillna("Missing")
        counts = values.value_counts()
        levels = sorted(counts.index, key=lambda level: (-counts[level], level))
        for level in levels[1:]:
            columns[f"{name}={level}"] = (values == level).astype(float)

    for f in spec.features:
        if f.role == "covariate":
            for column in feature_columns(f):
                columns[column] = table[column].astype(float)

    X = pd.DataFrame(columns, index=table.index)
    issues = []
    for column in list(X.columns):
        found = check_feature_variation(column, X[column])
        issues += found
        for i in found:
            if i["code"] == "constant_feature":
                X = X.drop(columns=column)
    return X, issues


def propensity_scores(X: pd.DataFrame, exposure: np.ndarray) -> np.ndarray:
    """Each patient's probability of being treated, from logistic regression on X.

    The model is only used to predict, so its coefficients and their
    standard errors are never reported.
    """
    exog = sm.add_constant(X, has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("error", PerfectSeparationWarning)
        try:
            fit = sm.GLM(exposure, exog, family=sm.families.Binomial()).fit()
        except (PerfectSeparationWarning, np.linalg.LinAlgError) as e:
            raise AnalysisError(
                "The covariates separate treated patients from controls completely, so "
                "there are no comparable controls for some treated patients. Check for a "
                "covariate that only one group can have.") from e
    return np.asarray(fit.predict(exog))


def match_pairs(scores: np.ndarray, exposure: np.ndarray, seed: int) -> list[tuple[int, int]]:
    """Greedy 1:1 nearest-neighbour matching on the logit of the propensity score.

    Returns (treated row, control row) pairs, as positions in the arrays.

    Treated patients are taken in random order, and each takes the closest
    control not yet taken if it is within the caliper. A control is used at
    most once. Distances are on the logit scale, which spreads out scores
    near 0 and 1, where a small difference in probability is a large
    difference in odds.

    Greedy matching depends on the order. A random order avoids always
    giving the best controls to the patients most (or least) likely to be
    treated; Austin (2014) found it performs as well as the alternatives.

    Treated patients with no control within the caliper stay unmatched, so
    the estimate describes the treated who could be matched. The caller
    reports how many were left out.
    """
    clipped = np.clip(scores, 1e-9, 1 - 1e-9)
    logit = np.log(clipped / (1 - clipped))
    caliper = CALIPER_SD * np.std(logit)

    treated = np.flatnonzero(exposure == 1)
    controls = np.flatnonzero(exposure == 0)
    control_logit = logit[controls]
    available = np.ones(len(controls), dtype=bool)

    pairs = []
    for i in np.random.default_rng(seed).permutation(len(treated)):
        t = treated[i]
        distance = np.abs(control_logit - logit[t])
        distance[~available] = np.inf
        j = int(np.argmin(distance))
        if distance[j] <= caliper:
            available[j] = False
            pairs.append((int(t), int(controls[j])))
    return pairs


def balance(X: pd.DataFrame, exposure: np.ndarray, matched: np.ndarray) -> list[dict]:
    """Means and standardised mean differences of every covariate, before and after matching.

    matched is a true/false array marking the rows in the matched cohort.
    The SMD is the difference in means divided by the pooled standard
    deviation. Both SMDs use the standard deviation from before matching,
    so a change in SMD reflects a change in the difference between the
    groups, not in how spread out they are.
    """
    rows = []
    for column in X.columns:
        values = X[column].to_numpy()
        treated_before = values[exposure == 1]
        control_before = values[exposure == 0]
        treated_after = values[(exposure == 1) & matched]
        control_after = values[(exposure == 0) & matched]
        sd = np.sqrt((treated_before.var(ddof=1) + control_before.var(ddof=1)) / 2)
        rows.append({
            "covariate": column,
            "treated_mean_before": float(treated_before.mean()),
            "control_mean_before": float(control_before.mean()),
            "smd_before": _smd(treated_before, control_before, sd),
            "treated_mean_after": float(treated_after.mean()),
            "control_mean_after": float(control_after.mean()),
            "smd_after": _smd(treated_after, control_after, sd),
        })
    return rows


def _smd(treated: np.ndarray, control: np.ndarray, sd: float) -> float:
    if not sd > 0:
        return 0.0
    return float((treated.mean() - control.mean()) / sd)
