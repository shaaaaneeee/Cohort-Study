"""Build the SQL that turns a study into an analysis-ready table.

The query is a chain of CTEs:

    treated        exposed patients, indexed at their first exposure date
    treated_dates  the treated index dates, numbered so controls can draw one
    control_draws  everyone else in the person table, with a random draw
    controls       ... and the treated index date that draw picks
    cohort_base    treated and controls together
    cohort_person  ... with age at index and person attributes
    f_<name>       one CTE per inclusion criterion, computed on cohort_person
    cohort_flags   one true/false column per eligibility step
    cohort         the patients who pass every step
    f_<name>       one CTE per covariate and outcome, computed on cohort
    final SELECT   cohort LEFT JOIN every feature CTE

Whether a study is sound is decided in validator.py, and the repository
refuses to build a query for a study with errors. What this module checks
itself is that every name it writes into SQL is a plain identifier. It is
the last code to handle those names before the database, so it does not rely
on its callers. User-chosen values (filter values, inclusion thresholds,
coverage dates) never appear in the SQL text; they go into Params and are
sent as bound parameters.
"""
import re
from datetime import date, timedelta

from cohort_studio.features import FeatureSpec, StudySpec, feature_columns
from cohort_studio.mapping import Mapping, Source

_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$")

UNIT_MONTHS = {"months": 1, "years": 12}
GRAIN_MONTHS = {"month": 1, "quarter": 3, "year": 12}
DAYS_PER_YEAR = 365.25

# keep_if operators as SQL writes them. The keys are the only values
# KeepIf.op accepts, so a lookup here cannot produce anything else.
SQL_OPERATORS = {"==": "=", "!=": "<>", ">=": ">=", ">": ">", "<=": "<=", "<": "<"}


def name(text: str) -> str:
    """Return text unchanged if it is safe to place in SQL as a table or column name."""
    if not isinstance(text, str) or not _SAFE_NAME.match(text):
        raise ValueError(f"not a safe SQL name: {text!r}")
    return text


class Params:
    """Collects the values a query needs and hands out a placeholder for each."""

    def __init__(self, dialect):
        self.dialect = dialect
        self.values = {}

    def add(self, value) -> str:
        key = f"p{len(self.values) + 1}"
        self.values[key] = value
        return self.dialect.param(key)

    def add_list(self, values: list) -> str:
        placeholders = []
        for value in values:
            placeholders.append(self.add(value))
        return ", ".join(placeholders)


# ------------------------------------------------------------ time windows

def periods(f: FeatureSpec, source: Source, d) -> tuple[str, list[tuple[str, str]]]:
    """Where an event sits in time, and the bounds of each period of the window.

    Returns (position, [(low, high), ...]). An event belongs to period k when
    low_k <= position < high_k. A feature that is not periodised has a single
    period covering the whole window. Bounds are relative to c.index_date.

    On a day-granularity source positions are dates. On month and year
    sources they are month or year numbers, because those sources cannot
    place an event inside its month or year; Window in features.py explains
    why plain date arithmetic there would leak post-index events into
    pre-index windows.
    """
    w = f.window
    index = "c.index_date"
    event_date = f"e.{name(source.date)}"

    if source.granularity == "day":
        position = f"CAST({event_date} AS DATE)"
        if w.unit == "days":
            # Periodised day windows are refused by the validator.
            return position, [(d.add_days(index, w.from_), d.add_days(index, w.to + 1))]
        first = first_month(w.from_, w.unit)
        last = last_month(w.to, w.unit)
        if f.periodise is None:
            return position, [(_month_start(first, index, d), _month_end(last, index, d))]
        step = GRAIN_MONTHS[f.periodise.grain]
        bounds = []
        for k in range(f.periodise.n):
            bounds.append((_month_start(first + k * step, index, d),
                           _month_end(first + (k + 1) * step - 1, index, d)))
        return position, bounds

    if source.granularity == "month":
        position = d.month_number(f"CAST({event_date} AS DATE)")
        origin = d.month_number(index)
        per_unit = {"months": 1, "years": 12}
        per_grain = GRAIN_MONTHS
    else:
        position = f"CAST({event_date} AS INTEGER)"
        origin = d.year(index)
        per_unit = {"years": 1}
        per_grain = {"year": 1}

    start = w.from_ * per_unit[w.unit]
    if f.periodise is None:
        end = (w.to + 1) * per_unit[w.unit]
        return position, [(f"({origin} + ({int(start)}))", f"({origin} + ({int(end)}))")]
    step = per_grain[f.periodise.grain]
    bounds = []
    for k in range(f.periodise.n):
        bounds.append((f"({origin} + ({int(start + k * step)}))",
                       f"({origin} + ({int(start + (k + 1) * step)}))"))
    return position, bounds


def first_month(k: int, unit: str) -> int:
    """The first month of unit k, with month 0 being the index day (see Window)."""
    per = UNIT_MONTHS[unit]
    if k >= 1:
        return (k - 1) * per + 1
    if k <= -1:
        return k * per
    return 0


def last_month(k: int, unit: str) -> int:
    per = UNIT_MONTHS[unit]
    if k >= 1:
        return k * per
    if k <= -1:
        return (k + 1) * per - 1
    return 0


def _shift_months(index: str, n: int, d) -> str:
    if n == 0:
        return index
    return d.add_months(index, n)


def _month_start(k: int, index: str, d) -> str:
    """First day of month k from the index date. Month 1 starts the day after it."""
    if k >= 1:
        return d.add_days(_shift_months(index, k - 1, d), 1)
    if k == 0:
        return index
    return d.add_months(index, k)


def _month_end(k: int, index: str, d) -> str:
    """The day after the last day of month k. Month -1 ends the day before the index date."""
    if k >= 0:
        return d.add_days(_shift_months(index, k, d), 1)
    return _shift_months(index, k + 1, d)


def window_years(f: FeatureSpec) -> float:
    """Length of the whole window in years.

    A fixed length rather than each patient's own: every patient in the
    cohort is followed for the full window (see coverage), so the only
    difference between patients is whether their months have 28 or 31 days
    or their years 365 or 366.
    """
    w = f.window
    if w.unit == "days":
        return (w.to - w.from_ + 1) / DAYS_PER_YEAR
    months = last_month(w.to, w.unit) - first_month(w.from_, w.unit) + 1
    if w.from_ <= 0 <= w.to:
        # Month 0 is only the index day.
        return (months - 1) / 12 + 1 / DAYS_PER_YEAR
    return months / 12


def coverage_bounds(source: Source) -> tuple[object, object]:
    """The source's coverage in the units periods() uses, as (low, high).

    A window is covered when its first bound is at least low and its last
    (exclusive) bound is at most high. None means no limit on that side.
    On month and year sources only whole months or years count as covered:
    a table that ends on 30 June 2025 has an incomplete 2025.
    """
    c = source.coverage
    low = None
    high = None
    if source.granularity == "day":
        if c.start is not None:
            low = c.start
        if c.end is not None:
            high = c.end + timedelta(days=1)
    elif source.granularity == "month":
        if c.start is not None:
            low = _month_number(c.start) + (0 if c.start.day == 1 else 1)
        if c.end is not None:
            last_day_of_month = (c.end + timedelta(days=1)).day == 1
            high = _month_number(c.end) + (1 if last_day_of_month else 0)
    else:
        if c.start is not None:
            low = c.start.year + (0 if (c.start.month, c.start.day) == (1, 1) else 1)
        if c.end is not None:
            high = c.end.year + (1 if (c.end.month, c.end.day) == (12, 31) else 0)
    return low, high


def _month_number(d: date) -> int:
    # Same numbering as Dialect.month_number.
    return d.year * 12 + d.month - 1


# ----------------------------------------------------------------- features

def _aggregate(f: FeatureSpec, k: int) -> str:
    """SQL for the value of period k, over the rows of the `events` subquery."""
    in_period = f"period = {int(k)}"
    a = f.aggregation
    if a == "count":
        return f"COUNT(CASE WHEN {in_period} THEN 1 END)"
    if a == "distinct_count":
        return f"COUNT(DISTINCT CASE WHEN {in_period} THEN event_pos END)"
    if a == "binary":
        return f"MAX(CASE WHEN {in_period} THEN 1 ELSE 0 END)"
    if a == "sum":
        return f"SUM(CASE WHEN {in_period} THEN measure END)"
    if a == "mean":
        return f"AVG(CASE WHEN {in_period} THEN measure END)"
    if a == "max":
        return f"MAX(CASE WHEN {in_period} THEN measure END)"
    if a == "rate":
        # Events per person-year of the period.
        years = window_years(f)
        if f.periodise is not None:
            years = years / f.periodise.n
        return f"COUNT(CASE WHEN {in_period} THEN 1 END) / {float(years)!r}"
    raise ValueError(f"no SQL for aggregation {a!r}")


def feature_cte(f: FeatureSpec, source: Source, base: str, d, params: Params) -> str:
    """One CTE with a row per patient who has at least one matching event.

    Patients with none are missing from it. The final query fills them in
    (see fill_value), which is why every CTE is LEFT JOINed.
    """
    position, bounds = periods(f, source, d)
    conditions = [f"{position} >= {bounds[0][0]}", f"{position} < {bounds[-1][1]}"]
    for column in sorted(f.filters):
        placeholders = params.add_list(f.filters[column])
        # Compared as text so a triage level stored as the number 1 matches
        # the filter value "1"; the validator compares values the same way.
        conditions.append(f"{d.text('e.' + name(column))} IN ({placeholders})")

    if len(bounds) == 1:
        period = "1"
    else:
        branches = []
        for k, (low, high) in enumerate(bounds, start=1):
            branches.append(f"WHEN {position} >= {low} AND {position} < {high} THEN {k}")
        period = "CASE " + " ".join(branches) + " END"

    measure = "NULL"
    if f.measure is not None:
        measure = f"e.{name(f.measure)}"

    events = (f"SELECT c.patient_id, c.index_date, {position} AS event_pos, "
              f"{measure} AS measure, {period} AS period\n"
              f"        FROM {name(base)} c\n"
              f"        JOIN {name(source.table)} e ON e.{name(source.id)} = c.patient_id\n"
              f"        WHERE " + "\n          AND ".join(conditions))

    columns = feature_columns(f)
    outputs = []
    if f.aggregation == "time_to_first":
        outputs.append(f"{d.days_between('index_date', 'MIN(event_pos)')} AS {name(columns[0])}")
        outputs.append(f"1 AS {name(columns[1])}")
        group_by = "patient_id, index_date"
    else:
        for k, column in enumerate(columns, start=1):
            outputs.append(f"{_aggregate(f, k)} AS {name(column)}")
        group_by = "patient_id"

    return (f"{name('f_' + f.name)} AS (\n"
            f"    SELECT patient_id,\n           " + ",\n           ".join(outputs) + "\n"
            f"    FROM (\n        {events}\n    ) events\n"
            f"    GROUP BY {group_by}\n)")


def fill_value(f: FeatureSpec, column: str, source: Source, d) -> str:
    """What a patient with no matching events gets in this column.

    Zero for every aggregation, as the design asks. For count, binary, sum
    and rate that is simply true. For the mean or max of a measure it is a
    convention: a patient with no ED visits gets a mean length of stay of 0,
    the same as one whose visits were all very short. When a mean or max is
    used as a covariate, pair it with a count or binary feature over the same
    events so the model can tell "no events" apart from "short events".

    Time to first event is the exception: no event means the patient was
    censored at the end of the window, so the days column gets the last day
    of the window and the event column 0.
    """
    if f.aggregation == "time_to_first" and column.endswith("_days"):
        _, bounds = periods(f, source, d)
        return f"({d.days_between('c.index_date', bounds[-1][1])} - 1)"
    return "0"


# ------------------------------------------------------------------- cohort

def _cohort_ctes(study: StudySpec, mapping: Mapping, d, params: Params,
                 windowed: list[FeatureSpec]) -> tuple[list[str], list[tuple[str, str]]]:
    """CTEs from the exposure table down to `cohort`, and the eligibility steps.

    windowed is every feature whose windows must lie inside its source's
    coverage. The steps come back as (label, flag column) in the order they
    are applied, for the attrition counts.
    """
    exposure = None
    for x in mapping.exposure:
        if x.name == study.exposure:
            exposure = x
    person = mapping.person
    sources = mapping.feature_sources()
    pid = name(person.id)
    attributes = []
    for attribute in person.attributes:
        attributes.append(name(attribute))

    ctes = []
    # A patient who enrolled more than once is indexed at their first
    # enrolment. Indexing at a later one would count the time already spent
    # in the programme as look-back, and the programme's effect as baseline.
    ctes.append(
        f"treated AS (\n"
        f"    SELECT {name(exposure.id)} AS patient_id,\n"
        f"           MIN(CAST({name(exposure.index_date)} AS DATE)) AS index_date\n"
        f"    FROM {name(exposure.table)}\n"
        f"    WHERE {name(exposure.index_date)} IS NOT NULL\n"
        f"    GROUP BY {name(exposure.id)}\n)")

    # Controls have no enrolment date, so each is given the index date of a
    # randomly drawn treated patient. This puts both groups' index dates in
    # the same calendar period with the same spread. A fixed date such as
    # the start of the data would compare treated patients in, say, 2022
    # with controls in 2018, and ED use differs between those years for
    # reasons unrelated to the programme (COVID-19 among them).
    #
    # Known limitation: controls are people who never enrolled during the
    # whole data period. Someone who enrolls in 2024 cannot be a control in
    # 2021, although they were not enrolled then. That uses information from
    # after the index date to choose controls; see the synthetic data
    # generator for the conditions under which it causes no bias.
    ctes.append(
        "treated_dates AS (\n"
        "    SELECT index_date, ROW_NUMBER() OVER (ORDER BY index_date, patient_id) AS draw\n"
        "    FROM treated\n)")
    ctes.append(
        "treated_count AS (\n"
        "    SELECT NULLIF(COUNT(*), 0) AS n FROM treated\n)")
    # The draw is computed in its own CTE so the join below is on a plain
    # column. Joining on the expression itself stops the database from using
    # a hash join, and it compares every patient with every treated date.
    draw = d.random_draw(f"p.{pid}", study.seed, "n.n")
    ctes.append(
        f"control_draws AS (\n"
        f"    SELECT p.{pid} AS patient_id, {draw} AS draw\n"
        f"    FROM {name(person.table)} p\n"
        f"    CROSS JOIN treated_count n\n"
        f"    WHERE NOT EXISTS (SELECT 1 FROM treated x WHERE x.patient_id = p.{pid})\n)")
    ctes.append(
        "controls AS (\n"
        "    SELECT c.patient_id, t.index_date\n"
        "    FROM control_draws c\n"
        "    JOIN treated_dates t ON t.draw = c.draw\n)")
    ctes.append(
        "cohort_base AS (\n"
        "    SELECT patient_id, index_date, 1 AS exposure FROM treated\n"
        "    UNION ALL\n"
        "    SELECT patient_id, index_date, 0 AS exposure FROM controls\n)")

    person_columns = ""
    for attribute in attributes:
        person_columns += f",\n           p.{attribute}"
    age = d.age_years(f"CAST(p.{name(person.birth_date)} AS DATE)", "b.index_date")
    ctes.append(
        f"cohort_person AS (\n"
        f"    SELECT b.patient_id, b.index_date, b.exposure,\n"
        f"           p.{pid} IS NOT NULL AS has_person,\n"
        f"           {age} AS age{person_columns}\n"
        f"    FROM cohort_base b\n"
        f"    LEFT JOIN {name(person.table)} p ON p.{pid} = b.patient_id\n)")

    # Eligibility steps, applied to both groups alike. Treated patients
    # missing from the person table are dropped here rather than silently by
    # an inner join, so the attrition counts show how many there were.
    steps = [("Has a patient record", "c.has_person")]

    if study.age_min is not None or study.age_max is not None:
        tests = []
        if study.age_min is not None:
            tests.append(f"c.age >= {int(study.age_min)}")
        if study.age_max is not None:
            tests.append(f"c.age <= {int(study.age_max)}")
        if study.age_min is not None and study.age_max is not None:
            label = f"Aged {study.age_min} to {study.age_max} at index date"
        elif study.age_min is not None:
            label = f"Aged {study.age_min} or over at index date"
        else:
            label = f"Aged {study.age_max} or under at index date"
        steps.append((label, " AND ".join(tests)))

    for attribute in sorted(study.person_filters):
        values = study.person_filters[attribute]
        placeholders = params.add_list(values)
        steps.append((f"{attribute}: {', '.join(values)}",
                      f"{d.text('c.' + name(attribute))} IN ({placeholders})"))

    covered = []
    for f in windowed:
        source = sources[f.source]
        low, high = coverage_bounds(source)
        _, bounds = periods(f, source, d)
        if low is not None:
            covered.append(f"{bounds[0][0]} >= {params.add(low)}")
        if high is not None:
            covered.append(f"{bounds[-1][1]} <= {params.add(high)}")
    if covered:
        steps.append(("Data covers every look-back and follow-up window",
                      "\n               AND ".join(covered)))

    inclusion = []
    for f in study.features:
        if f.role == "inclusion":
            inclusion.append(f)
            ctes.append(feature_cte(f, sources[f.source], "cohort_person", d, params))
    joins = ""
    for f in inclusion:
        cte = name("f_" + f.name)
        joins += f"\n    LEFT JOIN {cte} ON {cte}.patient_id = c.patient_id"
        # Missing means no matching events, the same 0 the analysis table uses.
        value = f"COALESCE({cte}.{name(f.name)}, 0)"
        steps.append((f.label, f"{value} {SQL_OPERATORS[f.keep_if.op]} {params.add(f.keep_if.value)}"))

    flags = ""
    for k, (_, condition) in enumerate(steps, start=1):
        # A NULL (no birth date, say) fails the step rather than passing it.
        flags += f",\n           COALESCE(({condition}), FALSE) AS step_{k}"
    kept = ""
    for attribute in attributes:
        kept += f", c.{attribute}"
    ctes.append(
        f"cohort_flags AS (\n"
        f"    SELECT c.patient_id, c.index_date, c.exposure, c.age{kept}{flags}\n"
        f"    FROM cohort_person c{joins}\n)")

    passes = []
    for k in range(1, len(steps) + 1):
        passes.append(f"step_{k}")
    kept = ""
    for attribute in attributes:
        kept += f", {attribute}"
    ctes.append(
        f"cohort AS (\n"
        f"    SELECT patient_id, index_date, exposure, age{kept}\n"
        f"    FROM cohort_flags\n"
        f"    WHERE {' AND '.join(passes)}\n)")

    labelled = []
    for k, (label, _) in enumerate(steps, start=1):
        labelled.append((label, f"step_{k}"))
    return ctes, labelled


def _feature_select(features: list[FeatureSpec], mapping: Mapping, d,
                    params: Params) -> tuple[list[str], list[str], list[str]]:
    """CTEs, SELECT columns and LEFT JOINs that add features to the cohort."""
    sources = mapping.feature_sources()
    ctes = []
    columns = []
    joins = []
    for f in features:
        source = sources[f.source]
        ctes.append(feature_cte(f, source, "cohort", d, params))
        cte = name("f_" + f.name)
        joins.append(f"LEFT JOIN {cte} ON {cte}.patient_id = c.patient_id")
        for column in feature_columns(f):
            fill = fill_value(f, column, source, d)
            columns.append(f"COALESCE({cte}.{name(column)}, {fill}) AS {name(column)}")
    return ctes, columns, joins


def _query(ctes: list[str], columns: list[str], joins: list[str], order: str) -> str:
    return ("WITH " + ",\n".join(ctes) +
            "\nSELECT " + ",\n       ".join(columns) +
            "\nFROM cohort c" + "".join("\n" + j for j in joins) +
            f"\nORDER BY {order}")


# ------------------------------------------------------------------ queries

def analysis_query(study: StudySpec, mapping: Mapping, d) -> tuple[str, dict]:
    """The analysis-ready table: one row per patient in the final cohort.

    Columns: patient_id, index_date, exposure (1 treated, 0 control), age,
    each person attribute, person_years of the outcome window (count and
    rate outcomes), then the columns of every covariate and the outcome.
    Inclusion criteria have already been applied and are not repeated.
    """
    params = Params(d)
    ctes, _ = _cohort_ctes(study, mapping, d, params, study.features)

    outputs = []
    outcome = None
    for f in study.features:
        if f.role != "inclusion":
            outputs.append(f)
        if f.role == "outcome":
            outcome = f

    columns = ["c.patient_id", "c.index_date", "c.exposure", "c.age"]
    for attribute in mapping.person.attributes:
        columns.append(f"c.{name(attribute)}")
    if outcome is not None and outcome.aggregation != "time_to_first":
        # Person-time for the offset of a Poisson or negative binomial model.
        columns.append(f"{float(window_years(outcome))!r} AS person_years")

    feature_ctes, feature_columns_sql, joins = _feature_select(outputs, mapping, d, params)
    sql = _query(ctes + feature_ctes, columns + feature_columns_sql, joins,
                 "c.exposure DESC, c.patient_id")
    return sql, params.values


def attrition_query(study: StudySpec, mapping: Mapping, d) -> tuple[str, dict, list[str]]:
    """Patients left after each eligibility step, by group.

    Returns the SQL, its parameters and the step labels. The result has one
    row per exposure group, with n_0 for the starting population and n_k for
    the patients passing steps 1 to k.
    """
    params = Params(d)
    ctes, steps = _cohort_ctes(study, mapping, d, params, study.features)
    counts = ["exposure", "COUNT(*) AS n_0"]
    passed = []
    for k, (_, flag) in enumerate(steps, start=1):
        passed.append(flag)
        counts.append(f"SUM(CASE WHEN {' AND '.join(passed)} THEN 1 ELSE 0 END) AS n_{k}")
    sql = ("WITH " + ",\n".join(ctes) +
           "\nSELECT " + ",\n       ".join(counts) +
           "\nFROM cohort_flags\nGROUP BY exposure")
    labels = ["Starting population"]
    for label, _ in steps:
        labels.append(label)
    return sql, params.values, labels


def preview_query(study: StudySpec, feature: FeatureSpec, mapping: Mapping, d) -> tuple[str, dict]:
    """The study's cohort with one extra feature computed on it.

    The feature is never applied as a filter, even if it is an inclusion
    criterion: the point is to see its values before deciding on it. Its
    windows do count towards coverage, so the preview shows the cohort as it
    would be with the feature added. study should not already contain it.
    """
    params = Params(d)
    ctes, _ = _cohort_ctes(study, mapping, d, params, study.features + [feature])
    feature_ctes, columns, joins = _feature_select([feature], mapping, d, params)
    sql = _query(ctes + feature_ctes, ["c.patient_id", "c.exposure"] + columns, joins,
                 "c.patient_id")
    return sql, params.values


def distinct_values_query(table: str, column: str, d) -> str:
    """Every value a dimension takes in the data, as text."""
    return (f"SELECT DISTINCT {d.text(name(column))} AS value FROM {name(table)} "
            f"WHERE {name(column)} IS NOT NULL ORDER BY 1")
