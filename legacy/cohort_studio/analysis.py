"""Run a study's statistics on its analysis-ready table.

run_analysis() takes the table the repository built and the study spec and
returns what the results view shows: cohort sizes, covariate balance before
and after matching, the effect estimate from the model the outcome calls
for, a plain-English reading of it, and every warning. It does not know or
care where the table came from.
"""
import numpy as np
import pandas as pd
from lifelines import KaplanMeierFitter

from cohort_studio.features import FeatureSpec, StudySpec, feature_columns
from cohort_studio.matching import SMD_LIMIT, balance, covariate_matrix, match_pairs, propensity_scores
from cohort_studio.models import AnalysisError, fit_outcome, implied_model
from cohort_studio.validator import check_events_per_covariate, check_small_cells, issue

# Warn when more than this share of treated patients find no control within
# the caliper. The estimate then describes a noticeably different group from
# "everyone who enrolled".
UNMATCHED_LIMIT = 0.05


def run_analysis(table: pd.DataFrame, spec: StudySpec) -> dict:
    """Match, check balance, fit the outcome model and collect every warning.

    Returns a dict with:
        model           which model was fitted and why, and the estimate:
                        measure, estimate, ci_low, ci_high, p_value, and
                        dispersion (counts) or ph_p_value (Cox)
        cohort          patients per group before and after matching
        events          patients with the outcome per group, in the matched cohort
        balance         one row per covariate from matching.balance()
        issues          warnings about the data and the fit
        interpretation  one paragraph in plain English
        plots           data for the results charts: propensity (score
                        distributions, when matched), survival (Kaplan-Meier
                        curves, time-to-event outcomes) and periods (mean per
                        period, periodised outcomes); None where not relevant
    """
    outcome = None
    for f in spec.features:
        if f.role == "outcome":
            outcome = f
    if outcome is None:
        raise AnalysisError("The study has no outcome.")

    issues = []
    X, found = covariate_matrix(table, spec)
    issues += found
    complete = X.notna().all(axis=1).to_numpy()
    if not complete.all():
        issues.append(issue("warning", "missing_covariates",
                            f"{int((~complete).sum())} patients have a missing covariate value "
                            f"and are left out."))
    table = table[complete]
    X = X[complete]

    exposure = table["exposure"].to_numpy()
    n_treated = int((exposure == 1).sum())
    n_control = int((exposure == 0).sum())
    if n_treated == 0 or n_control == 0:
        raise AnalysisError(f"The cohort needs both groups; it has {n_treated} treated "
                            f"patients and {n_control} controls.")

    if X.shape[1] > 0:
        scores = propensity_scores(X, exposure)
        pairs = match_pairs(scores, exposure, spec.seed)
        if not pairs:
            raise AnalysisError("No treated patient has a control close enough to match.")
        rows = []
        groups = []
        for k, (t, c) in enumerate(pairs):
            rows += [t, c]
            groups += [k, k]
        matched = np.zeros(len(table), dtype=bool)
        matched[rows] = True
        balance_rows = balance(X, exposure, matched)
        issues += _balance_issues(balance_rows, n_treated, len(pairs))
        propensity = _propensity_distribution(scores, exposure, matched)
    else:
        # Nothing to match on: compare the groups as they are. Each patient
        # is their own cluster, which gives ordinary robust standard errors.
        rows = list(range(len(table)))
        groups = rows
        pairs = None
        balance_rows = []
        propensity = None
        issues.append(issue("warning", "no_covariates",
                            "No covariates were chosen, so the groups are compared as they "
                            "are, without matching or adjustment. The estimate is likely to "
                            "be confounded."))

    needed = ["exposure"] + feature_columns(outcome)
    if "person_years" in table.columns:
        needed.append("person_years")
    data = pd.concat([X, table[needed]], axis=1).iloc[rows]
    fitted = fit_outcome(data, outcome, list(X.columns), np.asarray(groups))
    issues += fitted.pop("issues")

    events, model_events = _events(data, outcome)
    issues += check_events_per_covariate(model_events, fitted["parameters"])

    matched_treated = int((data["exposure"] == 1).sum())
    matched_control = int((data["exposure"] == 0).sum())
    issues += check_small_cells({
        "treated patients analysed": matched_treated,
        "control patients analysed": matched_control,
        "treated patients with the outcome": events["treated"],
        "control patients with the outcome": events["control"],
    })

    model = implied_model(outcome)
    model.update(fitted)
    return {
        "model": model,
        "cohort": {"treated": n_treated, "control": n_control,
                   "treated_matched": matched_treated, "control_matched": matched_control,
                   "matched": pairs is not None},
        "events": events,
        "balance": balance_rows,
        "issues": issues,
        "interpretation": interpret(model, outcome, pairs is not None),
        "plots": {"propensity": propensity,
                  "survival": _survival_curves(data, outcome),
                  "periods": _period_means(data, outcome)},
    }


def _balance_issues(balance_rows: list[dict], n_treated: int, n_pairs: int) -> list[dict]:
    issues = []
    for row in balance_rows:
        if abs(row["smd_after"]) >= SMD_LIMIT:
            issues.append(issue("warning", "imbalance",
                                f"'{row['covariate']}' is still imbalanced after matching "
                                f"(standardised mean difference {row['smd_after']:.2f}). The "
                                f"outcome model adjusts for it, but the estimate leans more on "
                                f"that model being right."))
    unmatched = n_treated - n_pairs
    if unmatched > UNMATCHED_LIMIT * n_treated:
        issues.append(issue("warning", "unmatched_treated",
                            f"{unmatched} of {n_treated} treated patients "
                            f"({unmatched / n_treated:.0%}) had no comparable control and are "
                            f"left out. The estimate applies to the treated who could be "
                            f"matched, who are likely to be less unusual than those left out."))
    return issues


def _events(data: pd.DataFrame, outcome: FeatureSpec) -> tuple[dict, int]:
    """Patients with the outcome in each group, and the event count the model's EPV check uses.

    What counts as an "event" for the events-per-coefficient rule depends on
    the model (see validator.check_events_per_covariate): for a yes/no
    outcome the rarer of yes and no, for time to event the patients with an
    event, and for counts the patients with at least one event, because
    repeat events in one patient add less information than new patients.
    """
    columns = feature_columns(outcome)
    if outcome.aggregation == "time_to_first":
        has_event = data[columns[1]] > 0
    else:
        has_event = (data[columns] > 0).any(axis=1)
    events = {"treated": int(has_event[data["exposure"] == 1].sum()),
              "control": int(has_event[data["exposure"] == 0].sum())}
    total = events["treated"] + events["control"]
    if outcome.aggregation == "binary" and outcome.periodise is None:
        return events, min(total, len(data) - total)
    return events, total


def _propensity_distribution(scores: np.ndarray, exposure: np.ndarray, matched: np.ndarray,
                             bands: int = 20) -> dict:
    """Share of each group in each propensity score band, before and after matching.

    Shares rather than counts, because the control group is usually many
    times larger and the question is whether the two distributions overlap:
    treated patients in bands where hardly any controls lie have no good
    comparison. The bands run from 0 to just above the highest score.
    """
    top = max(0.05, float(np.ceil(scores.max() * 20) / 20))
    edges = np.linspace(0, top, bands + 1)

    def shares(mask: np.ndarray) -> list[float]:
        counts = np.histogram(scores[mask], edges)[0]
        return (counts / max(int(counts.sum()), 1)).tolist()

    return {"edges": edges.tolist(),
            "before": {"treated": shares(exposure == 1), "control": shares(exposure == 0)},
            "after": {"treated": shares((exposure == 1) & matched),
                      "control": shares((exposure == 0) & matched)}}


def _survival_curves(data: pd.DataFrame, outcome: FeatureSpec, points: int = 60) -> dict | None:
    """Kaplan-Meier curves for the analysed groups, on a shared grid of days.

    Shown next to a hazard ratio because the ratio assumes the curves
    separate steadily; curves that cross or converge are the visible sign
    that a single ratio summarises them poorly.
    """
    if outcome.aggregation != "time_to_first":
        return None
    days, event = feature_columns(outcome)
    grid = np.unique(np.linspace(0, float(data[days].max()), points).round())
    curves = {"days": grid.tolist()}
    for arm, group in ((1, "treated"), (0, "control")):
        rows = data[data["exposure"] == arm]
        fitter = KaplanMeierFitter().fit(rows[days], rows[event])
        curves[group] = fitter.survival_function_at_times(grid).to_numpy().tolist()
    return curves


def _period_means(data: pd.DataFrame, outcome: FeatureSpec) -> dict | None:
    """Mean outcome per patient in each period, by group, for periodised outcomes."""
    if outcome.periodise is None:
        return None
    columns = feature_columns(outcome)
    means = {"periods": columns}
    for arm, group in ((1, "treated"), (0, "control")):
        rows = data[data["exposure"] == arm]
        means[group] = rows[columns].mean().tolist()
    return means


def interpret(model: dict, outcome: FeatureSpec, matched: bool) -> str:
    """One paragraph reading the estimate in plain English."""
    estimate = model["estimate"]
    what = {"Odds ratio": "odds", "Rate ratio": "rate", "Hazard ratio": "hazard"}[model["measure"]]
    if estimate < 1:
        change = f"{(1 - estimate):.0%} lower"
    else:
        change = f"{(estimate - 1):.0%} higher"
    if model["p_value"] < 0.001:
        p = "p < 0.001"
    else:
        p = f"p = {model['p_value']:.3f}"
    compared = "matched controls" if matched else "controls"
    if model["ci_low"] > 1 or model["ci_high"] < 1:
        certainty = "The 95% confidence interval does not include 1."
    else:
        certainty = ("The 95% confidence interval includes 1, so the data are consistent "
                     "with no effect.")
    return (f"{model['measure']} {estimate:.2f} (95% CI {model['ci_low']:.2f} to "
            f"{model['ci_high']:.2f}, {p}). The treated group's {what} of "
            f"\"{outcome.label}\" was {change} than that of {compared}. {certainty} "
            f"Model: {model['name']}.")
