"""Load the mapping config that binds physical tables and columns to logical roles.

The rest of the code never names a table or column directly; it asks the
Mapping. These names end up inside generated SQL and the config is the only
place they come from, so every one of them is checked against a plain
identifier pattern when the config is loaded.
"""
from datetime import date
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# Letters, digits and underscores, not starting with a digit. Anything else
# (spaces, quotes, semicolons, comment markers) is refused rather than escaped,
# so a name that passes can be placed in SQL without further handling.
Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", max_length=128)]

# Tables may be qualified as schema.table or catalog.schema.table; Databricks
# Unity Catalog uses three parts. Each part follows the identifier rule.
TableName = Annotated[str, StringConstraints(
    pattern=r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,2}$", max_length=400)]

# The finest date resolution a table records. A year-granularity table only
# knows the calendar year an event happened in, not where in the year.
Granularity = Literal["day", "month", "year"]

# Fixed names under which features and value lookups refer to the condition
# and person tables. Event sources may not reuse them.
CONDITION_SOURCE = "condition"
PERSON_SOURCE = "person"


class Dimension(BaseModel):
    """A categorical column that users can filter a source on."""
    model_config = ConfigDict(extra="forbid", coerce_numbers_to_str=True)

    label: str
    # "auto": allowed values are discovered from the data with a cached
    # SELECT DISTINCT, so new categories appear without a code change.
    # A list pins the allowed values instead.
    values: Literal["auto"] | list[str] = "auto"


class Coverage(BaseModel):
    """The dates a table is complete for.

    A patient with no events in a window is counted as zero, which is only
    true if the table would have recorded events in that window. A patient
    indexed in early 2018 whose look-back reaches into 2017, before the ED
    extract starts, would look as if they had never attended ED. So the
    cohort keeps only patients whose every window lies inside the coverage
    of its source (complete look-back and complete follow-up).

    A bound left out means the table is complete in that direction, for
    example a condition table that holds every diagnosis ever made.
    """
    model_config = ConfigDict(extra="forbid")

    start: date | None = None
    end: date | None = None

    @model_validator(mode="after")
    def _check_order(self) -> "Coverage":
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError(f"coverage start {self.start} is after end {self.end}")
        return self


class Measure(BaseModel):
    """A numeric column that users can aggregate, and the aggregations allowed on it."""
    model_config = ConfigDict(extra="forbid")

    label: str
    agg: list[Literal["sum", "mean", "max"]] = Field(min_length=1)


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: TableName
    id: Identifier
    birth_date: Identifier
    # One value per patient, used as baseline characteristics. That is only
    # correct if the value describes the patient at the index date. A snapshot
    # taken at extraction time (residence status, for example) can reflect a
    # change that happened after it.
    attributes: list[Identifier] = []


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Name shown in the UI; the code name is used if it is left out.
    label: str | None = None
    table: TableName
    id: Identifier
    concept: Identifier
    date: Identifier
    granularity: Granularity
    coverage: Coverage = Coverage()


class Source(BaseModel):
    """An event table: one row per event, with a date and optional dimensions and measures.

    The date column holds a date for day and month granularity, and the
    calendar year as a number for year granularity (like diagnosis_year).
    """
    model_config = ConfigDict(extra="forbid")

    name: Identifier
    label: str | None = None
    table: TableName
    id: Identifier
    date: Identifier
    granularity: Granularity
    coverage: Coverage = Coverage()
    dimensions: dict[Identifier, Dimension] = {}
    measures: dict[Identifier, Measure] = {}


class Exposure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Identifier
    label: str | None = None
    table: TableName
    id: Identifier
    index_date: Identifier


class Backend(BaseModel):
    """Which database the tables live in. Switching backends is a change here."""
    model_config = ConfigDict(extra="forbid")

    dialect: Literal["duckdb"]
    # Path to the DuckDB file. load_mapping reads a relative path from the
    # directory of the config file, so the app can be started from anywhere.
    database: str


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: Identifier
    backend: Backend
    person: Person
    condition: Condition
    sources: list[Source] = []
    exposure: list[Exposure] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_names(self) -> "Mapping":
        seen = set()
        for source in self.sources:
            if source.name in (CONDITION_SOURCE, PERSON_SOURCE):
                raise ValueError(f"source name '{source.name}' is reserved")
            if source.name in seen:
                raise ValueError(f"source '{source.name}' is defined twice")
            seen.add(source.name)

        exposure_names = [e.name for e in self.exposure]
        if len(set(exposure_names)) != len(exposure_names):
            raise ValueError("exposure names must be unique")
        return self

    def feature_sources(self) -> dict[str, Source]:
        """Every table a feature can draw events from, keyed by the name features use.

        The condition table is presented as one more source, named "condition",
        whose only dimension is the condition name. The validator and the SQL
        generator can then treat it like any event table, and its year
        granularity is enforced by the same rule as everything else.
        """
        c = self.condition
        by_name = {
            CONDITION_SOURCE: Source(
                name=CONDITION_SOURCE, label=c.label, table=c.table, id=c.id, date=c.date,
                granularity=c.granularity, coverage=c.coverage,
                dimensions={c.concept: Dimension(label="Condition")}),
        }
        for source in self.sources:
            by_name[source.name] = source
        return by_name


def load_mapping(path: str | Path) -> Mapping:
    """Read a mapping YAML file and check it. Raises pydantic.ValidationError on any problem."""
    # safe_load builds only dicts, lists and scalars. yaml.load would construct
    # arbitrary Python objects from tags in the file.
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    mapping = Mapping.model_validate(raw)
    database = Path(mapping.backend.database)
    if not database.is_absolute():
        mapping.backend.database = str((Path(path).parent / database).resolve())
    return mapping
