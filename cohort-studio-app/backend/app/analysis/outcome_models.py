"""Choose and fit the outcome model.

implied_model() names the model a study's outcome calls for without reading
any data, so the UI can show it while the study is being built.
fit_outcome() fits that model to the matched cohort.

Every model is adjusted the same way:

  - The exposure and every covariate are in the model. Matching removes most
    of the difference between the groups and the covariates remove what is
    left. Matching first also makes the estimate depend much less on getting
    the regression's form exactly right (Ho, Imai, King and Stuart, 2007).
  - Standard errors are clustered on the matched pair. Matched patients are
    more alike than two random patients, and ignoring that misstates the
    uncertainty (Austin, 2011). Clustered (sandwich) standard errors also
    stay valid when the outcome varies more than the model assumes, which
    matters for counts that are overdispersed but fall below the switch to
    negative binomial.

Odds ratios and hazard ratios are conditional on the covariates in the
model. Unlike a rate ratio, they change when a covariate that predicts the
outcome is added or removed, even one that is perfectly balanced. So the
odds ratio reported here is not the one you would get by comparing the raw
proportions of the matched groups, and both are correct answers to slightly
different questions.
"""

import warnings
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from lifelines import CoxPHFitter
from lifelines.exceptions import ConvergenceWarning as LifelinesConvergenceWarning
from lifelines.statistics import proportional_hazard_test
from statsmodels.tools.sm_exceptions import ConvergenceWarning

from app.analysis.validation import issue
from app.schemas.study import FeatureSpec, feature_columns

# Pearson chi-square divided by its degrees of freedom is 1 when counts vary
# as much as Poisson says they should. Above 1.5 the counts are clearly more
# spread out, and negative binomial, which has a parameter for the extra
# spread, describes them better. This is a rule of thumb, not a test.
DISPERSION_LIMIT = 1.5

# The proportional hazards check flags the hazard ratio when the Schoenfeld
# residual test for the exposure has p below this.
PH_P_LIMIT = 0.05


def implied_model(outcome: FeatureSpec) -> dict:
    """The model this outcome calls for, with the reason, before any data is read."""
    if outcome.periodise is not None:
        return {
            "model": "gee",
            "measure": "Rate ratio",
            "name": "GEE Poisson regression, exchangeable correlation",
            "reason": f"The outcome is counted in {outcome.periodise.n} periods per patient. "
            f"Periods from the same patient are correlated, so they are not "
            f"independent observations, and a model that treated them as "
            f"independent would understate the uncertainty.",
        }
    if outcome.aggregation == "binary":
        return {
            "model": "logistic",
            "measure": "Odds ratio",
            "name": "Logistic regression",
            "reason": "The outcome is yes or no for each patient.",
        }
    if outcome.aggregation == "time_to_first":
        return {
            "model": "cox",
            "measure": "Hazard ratio",
            "name": "Cox proportional hazards",
            "reason": "The outcome is the time to the first event, with patients who have "
            "no event censored at the end of the window.",
        }
    return {
        "model": "count",
        "measure": "Rate ratio",
        "name": "Poisson regression, or negative binomial if the counts are overdispersed",
        "reason": f"The outcome is a count of events per patient. Poisson is used unless "
        f"the counts vary much more than Poisson allows (Pearson dispersion "
        f"above {DISPERSION_LIMIT}), in which case negative binomial.",
    }


def fit_outcome(
    data: pd.DataFrame, outcome: FeatureSpec, covariates: list[str], groups: np.ndarray
) -> dict:
    """Fit the outcome model to the matched cohort.

    data has one row per patient with the exposure, the covariate columns,
    the outcome's columns and person_years. groups gives each row's matched
    pair. Returns the model's name, the effect measure and its estimate,
    95% confidence interval and p-value, the number of coefficients, and a
    list of issues.
    """
    kind = implied_model(outcome)["model"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if kind == "logistic":
            result = _logistic(data, outcome, covariates, groups)
        elif kind == "count":
            result = _count(data, outcome, covariates, groups)
        elif kind == "cox":
            result = _cox(data, outcome, covariates, groups)
        else:
            result = _gee(data, outcome, covariates, groups)

    for w in caught:
        if issubclass(w.category, (ConvergenceWarning, LifelinesConvergenceWarning)):
            result["issues"].append(
                issue(
                    "warning",
                    "not_converged",
                    f"The {result['name']} model did not converge cleanly ({w.message}). "
                    f"Treat the estimate with caution; fewer covariates may help.",
                )
            )
        else:
            warnings.warn(w.message, w.category, stacklevel=2)
    return result


def _ratio(fit: Any, name: str, measure: str, parameters: int) -> dict[str, Any]:
    low, high = fit.conf_int().loc["exposure"]
    return {
        "name": name,
        "measure": measure,
        "estimate": float(np.exp(fit.params["exposure"])),
        "ci_low": float(np.exp(low)),
        "ci_high": float(np.exp(high)),
        "p_value": float(fit.pvalues["exposure"]),
        "parameters": parameters,
        "issues": [],
    }


def _design(data: pd.DataFrame, covariates: list[str]) -> pd.DataFrame:
    return sm.add_constant(data[["exposure", *covariates]].astype(float), has_constant="add")


def _counts(values: pd.Series, outcome: FeatureSpec, years: float | pd.Series) -> pd.Series:
    # A rate outcome holds events per person-year. The models need the
    # counts themselves, with person-time as the offset, so turn it back.
    if outcome.aggregation == "rate":
        return (values * years).round()
    return values


def _logistic(
    data: pd.DataFrame, outcome: FeatureSpec, covariates: list[str], groups: np.ndarray
) -> dict[str, Any]:
    y = data[outcome.name]
    fit = sm.GLM(y, _design(data, covariates), family=sm.families.Binomial()).fit(
        cov_type="cluster", cov_kwds={"groups": groups}
    )
    return _ratio(fit, "Logistic regression", "Odds ratio", 1 + len(covariates))


def _count(
    data: pd.DataFrame, outcome: FeatureSpec, covariates: list[str], groups: np.ndarray
) -> dict[str, Any]:
    X = _design(data, covariates)
    years = data["person_years"]
    y = _counts(data[outcome.name], outcome, years)
    # log(person-time) as an offset makes the coefficients log rate ratios,
    # events per person-year, rather than log ratios of raw counts.
    poisson = sm.GLM(y, X, family=sm.families.Poisson(), offset=np.log(years)).fit(
        cov_type="cluster", cov_kwds={"groups": groups}
    )
    dispersion = float(poisson.pearson_chi2 / poisson.df_resid)

    if dispersion > DISPERSION_LIMIT:
        # NB2: variance = mean + alpha * mean^2, which is what Poisson counts
        # with a gamma-distributed patient-level rate produce. The optimiser
        # can try values where the log-likelihood is undefined on its way to
        # the answer, and numpy warns each time; what matters is whether it
        # converged in the end, which is checked below.
        with np.errstate(divide="ignore", invalid="ignore"):
            nb = sm.NegativeBinomial(y, X, exposure=years).fit(
                disp=0, maxiter=200, cov_type="cluster", cov_kwds={"groups": groups}
            )
        result = _ratio(
            nb,
            f"Negative binomial regression (Poisson dispersion "
            f"{dispersion:.2f} > {DISPERSION_LIMIT})",
            "Rate ratio",
            1 + len(covariates),
        )
        result["model"] = "negative_binomial"
        if not nb.mle_retvals.get("converged", True):
            result["issues"].append(
                issue(
                    "warning",
                    "not_converged",
                    "The negative binomial model did not converge. Treat the estimate with "
                    "caution; fewer covariates may help.",
                )
            )
    else:
        result = _ratio(
            poisson,
            f"Poisson regression (dispersion {dispersion:.2f})",
            "Rate ratio",
            1 + len(covariates),
        )
        result["model"] = "poisson"
    result["dispersion"] = dispersion
    return result


def _cox(
    data: pd.DataFrame, outcome: FeatureSpec, covariates: list[str], groups: np.ndarray
) -> dict[str, Any]:
    days, event = feature_columns(outcome)
    frame = data[[days, event, "exposure", *covariates]].astype(float)
    frame["_pair"] = groups
    # Ties (two events on the same day) are handled by Efron's method,
    # lifelines' default and the more accurate of the usual two.
    cox = CoxPHFitter().fit(frame, duration_col=days, event_col=event, cluster_col="_pair")
    row = cox.summary.loc["exposure"]
    result: dict[str, Any] = {
        "name": "Cox proportional hazards",
        "measure": "Hazard ratio",
        "estimate": float(row["exp(coef)"]),
        "ci_low": float(row["exp(coef) lower 95%"]),
        "ci_high": float(row["exp(coef) upper 95%"]),
        "p_value": float(row["p"]),
        "parameters": 1 + len(covariates),
        "issues": [],
    }

    # Cox assumes the hazard ratio is the same throughout follow-up. The
    # scaled Schoenfeld residual test checks that for the exposure.
    ph = proportional_hazard_test(cox, frame, time_transform="rank")
    ph_p = float(ph.summary.loc["exposure", "p"])
    result["ph_p_value"] = ph_p
    if ph_p < PH_P_LIMIT:
        result["issues"].append(
            issue(
                "warning",
                "proportional_hazards",
                f"The hazard ratio appears to change over follow-up (Schoenfeld residual "
                f"test p = {ph_p:.3g}). The estimate is an average over the window; look at "
                f"how the survival curves separate before relying on it.",
            )
        )
    return result


def _gee(
    data: pd.DataFrame, outcome: FeatureSpec, covariates: list[str], groups: np.ndarray
) -> dict[str, Any]:
    # One row per patient and period instead of one per patient.
    parts = []
    for k, column in enumerate(feature_columns(outcome), start=1):
        part = data[["exposure", *covariates]].astype(float)
        part["y"] = data[column].to_numpy()
        part["period"] = k
        part["cluster"] = groups
        parts.append(part)
    long = pd.concat(parts, ignore_index=True)

    # Each period gets its own baseline rate, so a change in ED use over
    # follow-up that affects both groups (seasons, a pandemic wave) is not
    # mistaken for an effect. The exposure coefficient is then the rate
    # ratio averaged over the periods.
    assert outcome.periodise is not None  # implied_model picks GEE only for periodised outcomes
    period_terms = []
    for k in range(2, outcome.periodise.n + 1):
        long[f"period_{k}"] = (long["period"] == k).astype(float)
        period_terms.append(f"period_{k}")

    period_years = float(data["person_years"].iloc[0]) / outcome.periodise.n
    y = _counts(long["y"], outcome, period_years)
    X = sm.add_constant(long[["exposure", *covariates, *period_terms]], has_constant="add")
    # Clusters are matched pairs, which contain each patient's periods, so the
    # sandwich standard errors allow both for repeated measures on a patient
    # and for the matching. The exchangeable working correlation (every pair
    # of observations in a cluster equally correlated) is a simplification;
    # GEE estimates and their sandwich standard errors stay valid when it is
    # wrong, at some cost in precision.
    model = sm.GEE(
        y,
        X,
        groups=long["cluster"],
        family=sm.families.Poisson(),
        cov_struct=sm.cov_struct.Exchangeable(),
        offset=np.full(len(long), np.log(period_years)),
    )
    fit = model.fit()
    return _ratio(
        fit,
        "GEE Poisson regression, exchangeable correlation",
        "Rate ratio",
        1 + len(covariates) + len(period_terms),
    )
