"""Schema for user-defined features and for the study that contains them.

A feature is one covariate, outcome or inclusion criterion written as data:
which source, which events (filters), which time window around the index
date, and how to aggregate the events in that window. The classes here only
check that a spec is well-formed by itself. Whether it fits the dataset and
is a sound study design is decided in validator.py.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.mapping import Identifier

# Feature names become column names in the analysis-ready table. Lower case
# only, so two features cannot collide on a backend that ignores case.
FeatureName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", max_length=60)]

# What each aggregation produces per patient from the matching events in the
# window. The descriptions are shown in the UI.
AGGREGATIONS = {
    "count": "Number of events",
    "distinct_count": "Number of distinct dates with an event (two on one day count once)",
    "binary": "1 if there is at least one event, otherwise 0",
    "sum": "Sum of a numeric measure",
    "mean": "Mean of a numeric measure",
    "max": "Largest value of a numeric measure",
    "rate": "Events per person-year of the window",
    "time_to_first": "Days from the index date to the first event, censored at the end "
    "of the window (outcomes only)",
}
Aggregation = Literal[
    "count", "distinct_count", "binary", "sum", "mean", "max", "rate", "time_to_first"
]
MEASURE_AGGREGATIONS = ("sum", "mean", "max")


class Window(BaseModel):
    """A time window counted in whole units from the index date.

    Unit 0 is the index day itself. Positive units count forward from the day
    after it and negative units count back from the day before it. Both
    `from` and `to` are inclusive, so:
        from=-365, to=-1,  unit=days    the 365 days before the index date
        from=1,    to=365, unit=days    the 365 days after it
        from=-12,  to=-1,  unit=months  the 12 months before it
        from=1,    to=12,  unit=months  the 12 months after it, from the next day
    For days this simply means day k is the index date + k.

    The index day belongs to neither side. An ED visit on the day of
    enrolment may be the reason for the enrolment, so it is neither a clean
    baseline event nor an outcome of the programme.

    A source that records dates only by month or year cannot say where in
    that month or year an event fell. On such a source the index date and
    the event dates are both cut to the source's resolution before the
    window is applied, so unit 0 is the whole calendar month or year that
    contains the index date, and unit k is the one k steps from it. On the
    year-granularity condition table, from=-5, to=-1 is the five calendar
    years before the index year. Plain date arithmetic there would let events
    from later in the index month or year into a window that is meant to end
    before the index date.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True, serialize_by_alias=True)

    anchor: Literal["index"] = "index"
    # "from" is a Python keyword, so the attribute is from_; JSON and YAML use "from".
    from_: int = Field(alias="from")
    to: int
    unit: Literal["days", "months", "years"]

    @model_validator(mode="after")
    def _check_order(self) -> "Window":
        if self.from_ > self.to:
            raise ValueError(f"window 'from' ({self.from_}) is after 'to' ({self.to})")
        return self


class Periodise(BaseModel):
    """Split the window into n consecutive periods of one grain each.

    A periodised covariate becomes n columns. A periodised outcome becomes n
    repeated measurements per patient. Those are correlated within a patient,
    so they need a repeated-measures model rather than a plain GLM.
    """

    model_config = ConfigDict(extra="forbid")

    grain: Literal["month", "quarter", "year"]
    # A single period is the same as not periodising.
    n: int = Field(ge=2, le=120)


class KeepIf(BaseModel):
    """The test an inclusion criterion applies: keep a patient if `feature op value`.

    "Diabetes before index" is a binary feature with op "==" and value 1.
    "No asthma before index" is the same with value 0. There is no separate
    exclusion type.
    """

    model_config = ConfigDict(extra="forbid")

    op: Literal["==", "!=", ">=", ">", "<=", "<"]
    value: float


class FeatureSpec(BaseModel):
    """One covariate, outcome or inclusion criterion."""

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    name: FeatureName
    label: str = Field(min_length=1, max_length=200)
    source: Identifier
    # Keys are dimension columns of the source. Each keeps only events whose
    # value is in its list; leaving a key out means any value. An empty list
    # would select nothing, which is never what anyone means, so it is refused.
    # Values are compared as text, so triage level 1 and "1" are the same.
    filters: dict[Identifier, Annotated[list[str], Field(min_length=1)]] = {}
    window: Window
    aggregation: Aggregation
    measure: Identifier | None = None
    periodise: Periodise | None = None
    role: Literal["covariate", "outcome", "inclusion"]
    keep_if: KeepIf | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "FeatureSpec":
        needs_measure = self.aggregation in MEASURE_AGGREGATIONS
        if needs_measure and self.measure is None:
            raise ValueError(f"aggregation '{self.aggregation}' needs a measure")
        if not needs_measure and self.measure is not None:
            raise ValueError(f"aggregation '{self.aggregation}' does not use a measure")
        if self.role == "inclusion" and self.keep_if is None:
            raise ValueError("an inclusion criterion needs keep_if")
        if self.role != "inclusion" and self.keep_if is not None:
            raise ValueError("keep_if is only used by inclusion criteria")
        return self


def feature_columns(f: FeatureSpec) -> list[str]:
    """The columns a feature adds to the analysis-ready table.

    Usually one column named after the feature. Time to first event needs two
    (days, and whether the event happened or the patient was censored at the
    end of the window). A periodised feature has one column per period,
    numbered from the earliest: name_p1, name_p2, ...
    """
    if f.aggregation == "time_to_first":
        return [f"{f.name}_days", f"{f.name}_event"]
    if f.periodise is None:
        return [f.name]
    columns = []
    for k in range(1, f.periodise.n + 1):
        columns.append(f"{f.name}_p{k}")
    return columns


class StudySpec(BaseModel):
    """Everything a user chooses to define one study.

    The treatment group is everyone in the chosen exposure table, indexed at
    their exposure date. Selecting controls and giving them an index date is
    part of building the cohort, not of this spec.
    """

    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    exposure: Identifier
    # Controls are given pseudo index dates by a random draw. The seed makes
    # the draw repeatable, so running the same study twice gives the same cohort.
    seed: int = Field(0, ge=0, le=2**31 - 1)
    # Age in whole years at the index date.
    age_min: int | None = Field(None, ge=0, le=120)
    age_max: int | None = Field(None, ge=0, le=120)
    # Keys are person attributes from the mapping; matched like feature filters.
    person_filters: dict[Identifier, Annotated[list[str], Field(min_length=1)]] = {}
    # "age" or any person attribute, adjusted for alongside the feature covariates.
    person_covariates: list[Identifier] = []
    features: list[FeatureSpec] = []

    @model_validator(mode="after")
    def _check_ages(self) -> "StudySpec":
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError(f"age_min ({self.age_min}) is greater than age_max ({self.age_max})")
        return self
