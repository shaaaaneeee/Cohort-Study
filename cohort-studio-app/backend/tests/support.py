"""Helpers for tests: a test PostgreSQL, hand-made data, and an in-memory repository.

Tests that need a database load their data into a throwaway schema of the
database at TEST_DATABASE_URL (a role that may create schemas), and point a
copy of the mapping at it. Each run uses its own schema names, so runs do not
collide, and drops them at the end.
"""

import os
import uuid

import pandas as pd
import psycopg
from psycopg import sql
from sqlalchemy import Engine

from app.core.mapping import Mapping
from app.db.dialect import PostgresDialect
from app.db.repositories.cohort import SqlCohortRepository
from app.db.session import query_runner
from app.seed import synthetic
from app.seed.load import apply_schema, connect, load_tables

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
RUN_PREFIX = f"t_{uuid.uuid4().hex[:8]}_"
DATA_SCHEMA = "cohort"


def build_schema(label: str, tables: dict[str, pd.DataFrame]) -> str:
    """Load tables into a fresh schema of the test database. Returns the schema name."""
    assert TEST_DATABASE_URL, "TEST_DATABASE_URL is not set"
    schema = RUN_PREFIX + label
    with connect(TEST_DATABASE_URL) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        apply_schema(conn, schema)
        load_tables(conn, tables, schema)
    return schema


def drop_schemas() -> None:
    """Drop every schema this run created."""
    if not TEST_DATABASE_URL:
        return
    with connect(TEST_DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT nspname FROM pg_namespace WHERE starts_with(nspname, %s)", (RUN_PREFIX,)
        ).fetchall()
        for (schema,) in rows:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()


def mapping_in(mapping: Mapping, schema: str) -> Mapping:
    """A copy of the mapping whose tables are in another schema."""
    moved = mapping.model_copy(deep=True)

    def move(table: str) -> str:
        return f"{schema}.{table.split('.')[-1]}"

    moved.person.table = move(moved.person.table)
    moved.condition.table = move(moved.condition.table)
    for source in moved.sources:
        source.table = move(source.table)
    for exposure in moved.exposure:
        exposure.table = move(exposure.table)
    return moved


def repository_for(schema: str, mapping: Mapping, engine: Engine) -> SqlCohortRepository:
    """A repository on the data in schema, through the same code the app uses."""
    return SqlCohortRepository(mapping_in(mapping, schema), PostgresDialect(), query_runner(engine))


def admin_connection() -> psycopg.Connection:
    assert TEST_DATABASE_URL
    return connect(TEST_DATABASE_URL)


class ValuesRepository:
    """A repository that only knows dimension values, for tests that never build a cohort.

    The values are those of the synthetic data, so the demonstration scripts
    validate against them exactly as they would against the database.
    """

    VALUES = {
        ("person", "ethnicity"): sorted(synthetic.ETHNICITY),
        ("person", "gender"): ["F", "M"],
        ("person", "residence_status"): sorted(synthetic.RESIDENCE),
        ("condition", "condition_name"): sorted(synthetic.CONDITIONS),
        ("ed_episodes", "mode_of_arrival"): ["Own transport", "Private ambulance", "SCDF"],
        ("ed_episodes", "triage_level"): sorted(synthetic.TRIAGE),
        ("ed_episodes", "disposition"): ["Admitted", "Discharged", "Left without being seen"],
    }

    def __init__(self, mapping: Mapping):
        self.mapping = mapping

    def dimension_values(self, source: str, dimension: str) -> list[str]:
        if (source, dimension) not in self.VALUES:
            raise LookupError(f"'{dimension}' is not a dimension of {source}")
        return list(self.VALUES[(source, dimension)])

    def attrition_counts(self, spec: object) -> list[dict]:
        raise AssertionError("this test should not build a cohort")

    def feature_preview(self, feature: object, spec: object) -> dict:
        raise AssertionError("this test should not build a cohort")

    def analysis_table(self, spec: object) -> pd.DataFrame:
        raise AssertionError("this test should not build a cohort")


def hand_made_tables() -> dict[str, pd.DataFrame]:
    """Four patients, a member with no patient record, and twelve ED visits.

    Every treated patient enrols on 15 June 2021. Day numbers in the
    comments are days from that date.
    """
    patients = pd.DataFrame(
        [
            # T1 turns 61 the day after the index date, so is still 60.
            ("T1", "1960-06-16", "Chinese", "F", "Citizen"),
            # T2 turns 50 on the index date. T2 has no ED visits and no conditions.
            ("T2", "1971-06-15", "Malay", "M", "Citizen"),
            ("C1", "1950-01-01", "Chinese", "F", "PR"),
            # C2 is 17 at the index date.
            ("C2", "2004-01-01", "Indian", "M", "Citizen"),
        ],
        columns=["patient_id", "date_of_birth", "ethnicity", "gender", "residence_status"],
    )
    members = pd.DataFrame(
        [
            ("T1", "2021-06-15"),
            ("T1", "2022-03-01"),  # re-enrolment; the first enrolment is the index
            ("T2", "2021-06-15"),
            ("T9", "2021-06-15"),  # no patient record
        ],
        columns=["patient_id", "enrollment_date"],
    )
    episodes = pd.DataFrame(
        [
            ("T1", "E01", "2020-06-14", "SCDF", "P2", "Discharged", 1.0),  # day -366
            ("T1", "E02", "2020-06-15", "SCDF", "P2", "Admitted", 2.0),  # day -365
            ("T1", "E03", "2021-06-14", "Own transport", "P3", "Discharged", 4.0),  # day -1
            ("T1", "E04", "2021-06-15", "SCDF", "P1", "Admitted", 9.0),  # day 0
            ("T1", "E05", "2021-06-16", "SCDF", "P2", "Admitted", 5.0),  # day 1
            ("T1", "E06", "2021-06-16", "Own transport", "P3", "Discharged", 3.0),  # day 1 again
            ("T1", "E07", "2022-06-15", "Own transport", "P4", "Discharged", 1.5),  # day 365
            ("T1", "E08", "2022-06-16", "Own transport", "P4", "Discharged", 2.5),  # day 366
            ("C1", "E09", "2021-01-01", "SCDF", "P3", "Discharged", 6.0),  # day -165
            ("C1", "E10", "2021-05-31", "Own transport", "P3", "Discharged", 3.0),  # day -15, May
            ("C1", "E11", "2021-06-01", "Own transport", "P3", "Discharged", 3.0),  # day -14, June
            ("C2", "E12", "2021-03-01", "Own transport", "P3", "Discharged", 2.0),  # day -106
        ],
        columns=[
            "patient_id",
            "episode_id",
            "attendance_date",
            "mode_of_arrival",
            "triage_level",
            "disposition",
            "los_hours",
        ],
    )
    conditions = pd.DataFrame(
        [
            ("T1", "diabetes", 2020),  # the year before the index year
            ("T1", "copd", 2021),  # the index year: may be after the index date
            ("C1", "diabetes", 2021),
            ("C1", "asthma", 2015),
        ],
        columns=["patient_id", "condition_name", "diagnosis_year"],
    )
    return {
        "master_patient": patients,
        "program_members": members,
        "ed_episodes": episodes,
        "chronic_conditions": conditions,
    }
