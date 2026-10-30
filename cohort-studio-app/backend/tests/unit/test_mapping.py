"""Tests for loading the mapping config, including names that would be unsafe in SQL."""

from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from app.core.mapping import Mapping


@pytest.fixture
def raw(config_path) -> dict:
    """The example config as a plain dict, to be altered by each test."""
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_example_config_loads(mapping):
    assert mapping.dataset == "my_study"
    assert mapping.person.attributes == ["ethnicity", "gender", "residence_status"]
    assert mapping.exposure[0].index_date == "enrollment_date"
    ed = mapping.sources[0]
    assert ed.dimensions["triage_level"].values == "auto"
    assert ed.measures["los_hours"].agg == ["mean", "sum", "max"]


def test_condition_table_is_offered_as_a_year_granularity_source(mapping):
    sources = mapping.feature_sources()
    assert set(sources) == {"condition", "ed_episodes"}
    condition = sources["condition"]
    assert condition.table == "cohort.chronic_conditions"
    assert condition.granularity == "year"
    assert list(condition.dimensions) == ["condition_name"]


@pytest.mark.parametrize(
    "bad_table",
    [
        "master_patient; DROP TABLE master_patient",
        "master patient",
        "master_patient--",
        '"master_patient"',
        "a.b.c.d",
    ],
)
def test_unsafe_table_names_are_refused(raw, bad_table):
    raw["person"]["table"] = bad_table
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)


def test_qualified_table_names_are_accepted(raw):
    raw["person"]["table"] = "main.cohort.master_patient"
    assert Mapping.model_validate(raw).person.table == "main.cohort.master_patient"


@pytest.mark.parametrize(
    "path, bad_column",
    [
        (("person", "id"), "patient id"),
        (("person", "birth_date"), "date_of_birth)"),
        (("condition", "concept"), "1condition"),
    ],
)
def test_unsafe_column_names_are_refused(raw, path, bad_column):
    raw[path[0]][path[1]] = bad_column
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)


def test_unsafe_dimension_name_is_refused(raw):
    dims = raw["sources"][0]["dimensions"]
    dims["mode_of_arrival OR 1=1"] = dims.pop("mode_of_arrival")
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)


def test_unsafe_person_attribute_is_refused(raw):
    raw["person"]["attributes"].append("gender; --")
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)


@pytest.mark.parametrize("name", ["condition", "person"])
def test_reserved_source_names_are_refused(raw, name):
    raw["sources"][0]["name"] = name
    with pytest.raises(ValidationError, match="reserved"):
        Mapping.model_validate(raw)


def test_duplicate_source_is_refused(raw):
    raw["sources"].append(dict(raw["sources"][0]))
    with pytest.raises(ValidationError, match="defined twice"):
        Mapping.model_validate(raw)


def test_misspelt_key_is_refused(raw):
    # Without this a typo would silently drop every dimension of the source.
    raw["sources"][0]["dimesions"] = raw["sources"][0].pop("dimensions")
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)


def test_unknown_measure_aggregation_is_refused(raw):
    raw["sources"][0]["measures"]["los_hours"]["agg"] = ["median"]
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)


def test_pinned_numeric_values_are_read_as_text(raw):
    raw["sources"][0]["dimensions"]["triage_level"]["values"] = [1, 2, 3]
    m = Mapping.model_validate(raw)
    assert m.sources[0].dimensions["triage_level"].values == ["1", "2", "3"]


def test_the_mapping_names_a_dialect_but_holds_no_connection_settings(mapping, raw):
    assert mapping.backend.dialect == "postgres"
    # Connection settings come from the environment, never from this file.
    raw["backend"]["database"] = "postgresql://user:secret@host/db"
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)


def test_tables_live_in_the_cohort_schema(mapping):
    assert mapping.person.table == "cohort.master_patient"
    assert {s.table for s in mapping.feature_sources().values()} == {
        "cohort.chronic_conditions",
        "cohort.ed_episodes",
    }


def test_coverage_is_read_and_passed_to_the_condition_source(mapping):
    sources = mapping.feature_sources()
    assert sources["ed_episodes"].coverage.start == date(2018, 1, 1)
    assert sources["condition"].coverage.start is None
    assert sources["condition"].coverage.end == date(2025, 12, 31)


def test_coverage_ending_before_it_starts_is_refused(raw):
    raw["sources"][0]["coverage"] = {"start": "2025-01-01", "end": "2018-01-01"}
    with pytest.raises(ValidationError, match="after end"):
        Mapping.model_validate(raw)


def test_unknown_backend_is_refused(raw):
    raw["backend"]["dialect"] = "oracle"
    with pytest.raises(ValidationError):
        Mapping.model_validate(raw)
