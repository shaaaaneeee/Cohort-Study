"""Check a study design before it runs.

validate_study() looks only at the study spec and the mapping config, before
any data is read. It returns every problem it finds rather than stopping at
the first, so the UI can show them together. An issue with level "error"
blocks the analysis. A "warning" is reported next to the result.

The check_* functions at the end of the file need data (event counts,
feature values, cell counts) and are called once the analysis-ready table
exists.
"""

from collections.abc import Callable, Iterable
from collections.abc import Mapping as AbcMapping
from typing import Any

import pandas as pd

from app.core.mapping import PERSON_SOURCE, Mapping, Source
from app.schemas.study import FeatureSpec, StudySpec, feature_columns

# Returns the allowed values of one dimension, given (source name, column).
# The repository's dimension_values method has this signature.
ValueLookup = Callable[[str, str], list[str]]

# Columns every analysis-ready table has. A feature may not reuse these names.
FIXED_COLUMNS = {"patient_id", "index_date", "exposure", "age", "person_years"}

# Window units and period grains from finest to coarsest.
FINENESS = {"days": 0, "day": 0, "months": 1, "month": 1, "quarter": 2, "years": 3, "year": 3}

# Length in months of window units and period grains, used to check that a
# periodised window divides into whole periods.
MONTHS = {"months": 1, "month": 1, "quarter": 3, "years": 12, "year": 12}

# Outcome aggregations the model selector can handle:
#   binary                        logistic regression
#   count, distinct_count, rate   Poisson with person-time offset, or negative binomial
#   time_to_first                 Cox proportional hazards
#   periodised counts or rates    GEE for repeated measures
# A summed, averaged or maximum measure (total length of stay, say) has no
# model yet, so it is refused as an outcome rather than fitted with a wrong one.
OUTCOME_AGGREGATIONS = {"binary", "count", "distinct_count", "rate", "time_to_first"}
PERIODISED_OUTCOME_AGGREGATIONS = {"count", "distinct_count", "rate"}


def issue(level: str, code: str, message: str, feature: str | None = None) -> dict:
    """One problem found in a study. A plain dict so it can go straight into a JSON response."""
    return {"level": level, "code": code, "message": message, "feature": feature}


def issues_from_pydantic(errors: Iterable[AbcMapping[str, Any]]) -> list[dict]:
    """pydantic's errors, reworded as issues.

    loc is the path to the bad field, such as features > 0 > window > from.
    FastAPI puts "body" in front of it, which is left out.
    """
    issues = []
    for error in errors:
        where = []
        for part in error["loc"]:
            if part != "body":
                where.append(str(part))
        issues.append(issue("error", "invalid_request", f"{' > '.join(where)}: {error['msg']}"))
    return issues


# ------------------------------------------------------------ design rules


def validate_study(
    study: StudySpec, mapping: Mapping, dimension_values: ValueLookup | None = None
) -> list[dict]:
    """Return every problem with the study design, errors and warnings together.

    dimension_values is used to check filter values on dimensions whose values
    are discovered from the data ("auto"). Without it only values pinned in the
    mapping config are checked, so any caller about to build a query must
    pass it.
    """
    issues = []
    issues += _check_person_choices(study, mapping, dimension_values)

    sources = mapping.feature_sources()
    for feature in study.features:
        source = sources.get(feature.source)
        if source is None:
            issues.append(
                issue(
                    "error",
                    "unknown_source",
                    f"Source '{feature.source}' is not in the mapping config.",
                    feature.name,
                )
            )
            continue
        issues += _check_references(feature, source, dimension_values)
        issues += _check_granularity(feature, source)
        issues += _check_timing(feature)
        issues += _check_aggregation(feature)
        issues += _check_periods(feature)

    issues += _check_names(study, mapping)
    issues += _check_outcome_count(study)
    issues += _check_covariate_reused_as_outcome(study)
    return issues


def _check_person_choices(
    study: StudySpec, mapping: Mapping, lookup: ValueLookup | None
) -> list[dict]:
    issues = []
    exposure_names = [e.name for e in mapping.exposure]
    if study.exposure not in exposure_names:
        issues.append(
            issue(
                "error",
                "unknown_exposure",
                f"Exposure '{study.exposure}' is not in the mapping config "
                f"(known: {', '.join(exposure_names)}).",
            )
        )

    attributes = mapping.person.attributes
    for attribute, values in study.person_filters.items():
        if attribute not in attributes:
            issues.append(
                issue(
                    "error",
                    "unknown_person_attribute",
                    f"'{attribute}' is not a person attribute in the mapping config.",
                )
            )
        elif lookup is not None:
            issues += _unknown_values(
                PERSON_SOURCE, attribute, values, lookup(PERSON_SOURCE, attribute), None
            )

    for covariate in study.person_covariates:
        if covariate != "age" and covariate not in attributes:
            issues.append(
                issue(
                    "error",
                    "unknown_person_attribute",
                    f"'{covariate}' is neither 'age' nor a person attribute in the mapping config.",
                )
            )
    return issues


def _check_references(f: FeatureSpec, source: Source, lookup: ValueLookup | None) -> list[dict]:
    """Every dimension, value and measure a feature names must exist in the mapping.

    This is what keeps user input out of SQL: by the time a feature reaches
    the query builder, every name in it has been matched against the config.
    """
    issues = []
    for column, values in f.filters.items():
        dimension = source.dimensions.get(column)
        if dimension is None:
            issues.append(
                issue(
                    "error",
                    "unknown_dimension",
                    f"'{column}' is not a dimension of {source.name}.",
                    f.name,
                )
            )
            continue
        if isinstance(dimension.values, list):
            allowed = dimension.values
        elif lookup is not None:
            allowed = lookup(source.name, column)
        else:
            continue
        issues += _unknown_values(source.name, column, values, allowed, f.name)

    if f.measure is not None:
        measure = source.measures.get(f.measure)
        if measure is None:
            issues.append(
                issue(
                    "error",
                    "unknown_measure",
                    f"'{f.measure}' is not a measure of {source.name}.",
                    f.name,
                )
            )
        elif f.aggregation not in measure.agg:
            issues.append(
                issue(
                    "error",
                    "aggregation_not_allowed",
                    f"{f.measure} allows {', '.join(measure.agg)}, not {f.aggregation}.",
                    f.name,
                )
            )
    return issues


def _unknown_values(
    source: str, column: str, chosen: list[str], allowed: list[str], feature: str | None
) -> list[dict]:
    allowed_text = set()
    for value in allowed:
        allowed_text.add(str(value))
    unknown = []
    for value in chosen:
        if value not in allowed_text:
            unknown.append(value)
    if not unknown:
        return []
    return [
        issue(
            "error",
            "unknown_dimension_value",
            f"{source}.{column} has no value {', '.join(repr(v) for v in unknown)}.",
            feature,
        )
    ]


def _check_granularity(f: FeatureSpec, source: Source) -> list[dict]:
    # A window or period finer than the source records asks for information
    # the data does not have. "Diagnosed in the 90 days before index" on a
    # table that stores only the diagnosis year would force the query to guess
    # where in the year the diagnosis fell, and any guess either lets
    # post-index diagnoses in or drops pre-index ones.
    issues = []
    if FINENESS[f.window.unit] < FINENESS[source.granularity]:
        issues.append(
            issue(
                "error",
                "window_finer_than_source",
                f"{source.name} records dates by {source.granularity}, so the "
                f"window cannot be in {f.window.unit}.",
                f.name,
            )
        )
    if f.periodise is not None and FINENESS[f.periodise.grain] < FINENESS[source.granularity]:
        issues.append(
            issue(
                "error",
                "window_finer_than_source",
                f"{source.name} records dates by {source.granularity}, so it "
                f"cannot be split into {f.periodise.grain} periods.",
                f.name,
            )
        )
    if f.aggregation == "time_to_first" and source.granularity != "day":
        # The same problem in another form. Time to event is the number of
        # days from the index date to the event, and a source that records
        # only the month or year cannot supply it. Rounding each event to the
        # start of its period would make many events tie and would misstate,
        # by up to a whole period, how long each patient went without one.
        issues.append(
            issue(
                "error",
                "window_finer_than_source",
                f"{source.name} records dates by {source.granularity}, so time "
                f"to first event cannot be measured from it.",
                f.name,
            )
        )
    return issues


def _check_timing(f: FeatureSpec) -> list[dict]:
    w = f.window
    issues = []

    if f.role == "covariate" and w.to >= 0:
        # Look-ahead bias. A covariate must describe the patient before
        # exposure starts. A window that reaches the index date can pick up
        # events caused by the exposure, and adjusting for a consequence of
        # the exposure removes part of the effect being estimated. Unit 0
        # contains the index date, so `to` must be -1 or earlier. For a
        # year-granularity source unit 0 is the whole index year, much of
        # which can fall after the index date; cohort-poc counted diagnoses
        # from the index year as baseline and made exactly this mistake.
        issues.append(
            issue(
                "error",
                "covariate_lookahead",
                f"Covariate window ends at {w.to} {w.unit}; it must end before "
                f"the index date (to <= -1).",
                f.name,
            )
        )

    if f.role == "inclusion" and w.to >= 0:
        # Choosing patients by what happens after time zero conditions on the
        # future. "Had an ED visit in the year after enrollment" keeps only
        # patients who were alive and in contact with services, which builds
        # part of the outcome into who gets studied.
        issues.append(
            issue(
                "error",
                "inclusion_post_index",
                f"Inclusion criterion window ends at {w.to} {w.unit}; criteria "
                f"may only use information from before the index date.",
                f.name,
            )
        )

    if f.role == "outcome" and w.from_ <= 0:
        if f.aggregation == "time_to_first":
            # Survival time is counted from the index date. An event on or
            # before it would give a zero or negative time.
            issues.append(
                issue(
                    "error",
                    "outcome_window_before_index",
                    "Time to first event must use a window that starts after "
                    "the index date (from >= 1).",
                    f.name,
                )
            )
        else:
            # Events on or before the index date cannot have been caused by the
            # exposure. Counting them dilutes the estimate toward no effect.
            issues.append(
                issue(
                    "warning",
                    "outcome_window_before_index",
                    f"Outcome window starts at {w.from_} {w.unit}, so it counts "
                    f"events that happened before exposure started.",
                    f.name,
                )
            )
    return issues


def _check_aggregation(f: FeatureSpec) -> list[dict]:
    issues = []
    if f.aggregation == "time_to_first" and f.role != "outcome":
        issues.append(
            issue(
                "error",
                "aggregation_not_allowed",
                "Time to first event can only be used as an outcome.",
                f.name,
            )
        )

    if f.role == "outcome":
        if f.periodise is not None:
            allowed = PERIODISED_OUTCOME_AGGREGATIONS
        else:
            allowed = OUTCOME_AGGREGATIONS
        if f.aggregation not in allowed:
            issues.append(
                issue(
                    "error",
                    "outcome_aggregation_unsupported",
                    f"No model is defined for a {'periodised ' if f.periodise else ''}"
                    f"{f.aggregation} outcome. Use one of: "
                    f"{', '.join(sorted(allowed))}.",
                    f.name,
                )
            )

    if f.role == "inclusion" and f.periodise is not None:
        issues.append(
            issue(
                "error",
                "periodise_not_allowed",
                "An inclusion criterion needs one value per patient, so it cannot be periodised.",
                f.name,
            )
        )
    return issues


def _check_periods(f: FeatureSpec) -> list[dict]:
    if f.periodise is None:
        return []
    w, p = f.window, f.periodise
    if w.from_ <= 0 <= w.to:
        # Unit 0 is the index day on its own (or the index month or year on a
        # coarse source), so a period that contains it would be a different
        # length from the others and would mix before and after exposure.
        return [
            issue(
                "error",
                "periodise_window_mismatch",
                "A periodised window must lie entirely before or entirely after the index date.",
                f.name,
            )
        ]
    if w.unit == "days":
        # Months and quarters are not a fixed number of days, so a day-based
        # window cannot be cut into equal calendar periods.
        return [
            issue(
                "error",
                "periodise_window_mismatch",
                "A periodised feature needs a window in months or years.",
                f.name,
            )
        ]
    span = (w.to - w.from_ + 1) * MONTHS[w.unit]
    needed = p.n * MONTHS[p.grain]
    if span != needed:
        return [
            issue(
                "error",
                "periodise_window_mismatch",
                f"The window covers {span} months, but {p.n} {p.grain} periods need {needed}.",
                f.name,
            )
        ]
    return []


def _check_names(study: StudySpec, mapping: Mapping) -> list[dict]:
    reserved = set(FIXED_COLUMNS)
    for attribute in mapping.person.attributes:
        reserved.add(attribute.lower())

    issues = []
    seen = set()
    # Column name -> the feature that produces it. A periodised feature
    # "ed" produces ed_p1, ed_p2, ..., which another feature could also be called.
    owners: dict[str, str] = {}
    for f in study.features:
        if f.name in seen:
            issues.append(
                issue(
                    "error",
                    "duplicate_feature_name",
                    f"More than one feature is called '{f.name}'.",
                    f.name,
                )
            )
            continue
        seen.add(f.name)
        for column in feature_columns(f):
            if column in reserved:
                issues.append(
                    issue(
                        "error",
                        "reserved_feature_name",
                        f"'{column}' is already a column of the analysis table.",
                        f.name,
                    )
                )
            elif column in owners:
                issues.append(
                    issue(
                        "error",
                        "column_name_clash",
                        f"Features '{owners[column]}' and '{f.name}' would both "
                        f"create a column called '{column}'.",
                        f.name,
                    )
                )
            else:
                owners[column] = f.name
    return issues


def _check_outcome_count(study: StudySpec) -> list[dict]:
    # One study estimates one effect on one outcome. Several outcomes in one
    # run would each be a separate test, raising the chance that one of them
    # looks significant by luck, and nothing here corrects for that.
    n = 0
    for f in study.features:
        if f.role == "outcome":
            n += 1
    if n != 1:
        return [issue("error", "outcome_count", f"A study needs exactly one outcome; it has {n}.")]
    return []


def _event_definition(f: FeatureSpec) -> tuple:
    """What identifies the set of events a feature looks at: source, filters and window."""
    filters = []
    for column in sorted(f.filters):
        filters.append((column, tuple(sorted(set(f.filters[column])))))
    w = f.window
    return (f.source, tuple(filters), w.anchor, w.from_, w.to, w.unit)


def _check_covariate_reused_as_outcome(study: StudySpec) -> list[dict]:
    # Adjusting for the outcome itself. The covariate explains the outcome
    # almost perfectly, absorbs the exposure effect and pushes the estimate
    # toward no effect, or stops the model from fitting. Aggregation is
    # ignored on purpose: a binary covariate and a count outcome over the
    # same events are still the same information.
    covariates = {}
    for f in study.features:
        if f.role == "covariate":
            covariates[_event_definition(f)] = f.name

    issues = []
    for f in study.features:
        if f.role != "outcome":
            continue
        match = covariates.get(_event_definition(f))
        if match is not None:
            issues.append(
                issue(
                    "error",
                    "same_feature_covariate_and_outcome",
                    f"Outcome '{f.name}' counts the same events in the same window "
                    f"as covariate '{match}'.",
                    f.name,
                )
            )
    return issues


# ------------------------------------------------------------- data checks


def check_events_per_covariate(events: int, parameters: int, minimum: float = 10) -> list[dict]:
    """Warn when the outcome has too few events for the number of model coefficients.

    The usual rule of thumb is about 10 events per estimated coefficient
    (Peduzzi et al., 1996). Below it, logistic and Cox coefficients are biased
    away from zero and confidence intervals are unreliable. It is a guide, not
    a hard limit, which is why this is a warning.

    What the caller should count as events depends on the model:
        binary outcome   the smaller of events and non-events
        time to event    patients with the event
        counts           patients with at least one event; repeat events in
                         the same patient add less information than new patients
    parameters is every coefficient except the intercept: the exposure term,
    each dummy level of a categorical covariate, each periodised column.
    """
    if parameters <= 0:
        return []
    per_parameter = events / parameters
    if per_parameter >= minimum:
        return []
    return [
        issue(
            "warning",
            "low_events_per_covariate",
            f"{events} outcome events for {parameters} model coefficients is "
            f"{per_parameter:.1f} per coefficient, below the usual minimum of "
            f"{minimum:g}. Estimates may be unstable; consider fewer covariates or "
            f"a longer follow-up window.",
        )
    ]


def check_feature_variation(name: str, values: pd.Series, max_share: float = 0.99) -> list[dict]:
    """Warn when a feature is constant or nearly so.

    A constant column carries no information and makes the propensity score
    design matrix singular; cohort-poc crashed this way whenever an excluded
    diagnosis was also a covariate. A column where almost everyone has the
    same value gives an unstable coefficient and, in small samples, perfect
    separation.
    """
    present = values.dropna()
    if present.nunique() <= 1:
        return [
            issue(
                "warning",
                "constant_feature",
                f"'{name}' has the same value for every patient after filtering; "
                f"it cannot be used in a model.",
                name,
            )
        ]
    counts = present.value_counts(normalize=True)
    share = float(counts.iloc[0])
    if share >= max_share:
        return [
            issue(
                "warning",
                "near_constant_feature",
                f"{share:.1%} of patients have the same value of '{name}' "
                f"({counts.index[0]!r}). Its coefficient will be unstable.",
                name,
            )
        ]
    return []


def check_small_cells(counts: dict[str, int], threshold: int = 5) -> list[dict]:
    """Warn about any count to be reported that falls below the disclosure threshold.

    A small count in published output can identify individuals. Zero is not
    flagged because it describes nobody. Some data custodians also suppress
    zeros, or require secondary suppression so a hidden cell cannot be worked
    out by subtraction from totals; neither is done here.
    """
    issues = []
    for label, n in counts.items():
        if 0 < n < threshold:
            issues.append(
                issue(
                    "warning",
                    "small_cell",
                    f"'{label}' is {n}, below the suppression threshold of "
                    f"{threshold}. Suppress it before sharing the output.",
                )
            )
    return issues
