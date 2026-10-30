"""PostgreSQL-specific behaviour: the dialect's results, read-only access and the loader."""

import hashlib
from datetime import date

import pandas as pd
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.exceptions import DataSourceError
from app.db.dialect import PostgresDialect
from app.db.session import query_runner
from app.seed.load import apply_schema, load_tables, read_csv_folder
from tests.support import admin_connection, build_schema

D = PostgresDialect()


def scalar(engine: Engine, expression: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT {expression}"), params).scalar()


@pytest.mark.parametrize(
    ("birth", "at", "age"),
    [
        ("1960-06-16", "2021-06-15", 60),  # the day before the birthday
        ("1960-06-15", "2021-06-15", 61),  # on the birthday
        ("2000-02-29", "2021-02-28", 20),  # leap-day birthday, not yet reached
        ("2000-02-29", "2021-03-01", 21),
    ],
)
def test_age_is_completed_years(engine, birth, at, age):
    expression = D.age_years(f"DATE '{birth}'", f"DATE '{at}'")
    assert scalar(engine, expression) == age


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        ("2021-01-31", 1, date(2021, 2, 28)),  # month ends are clamped
        ("2020-01-31", 1, date(2020, 2, 29)),
        ("2021-06-15", -12, date(2020, 6, 15)),
        ("2021-06-15", 0, date(2021, 6, 15)),
    ],
)
def test_add_months(engine, start, months, expected):
    assert scalar(engine, D.add_months(f"DATE '{start}'", months)) == expected


def test_month_number_and_days_between(engine):
    assert scalar(engine, D.month_number("DATE '2021-06-15'")) == 2021 * 12 + 5
    assert scalar(engine, D.days_between("DATE '2021-06-15'", "DATE '2022-06-15'")) == 365
    assert scalar(engine, D.year("DATE '2021-06-15'")) == 2021


@pytest.mark.parametrize("patient_id", ["P000001", "C1", "00123", "x"])
@pytest.mark.parametrize("seed", [0, 7, 2**31 - 1])
def test_random_draw_matches_the_legacy_duckdb_formula(engine, patient_id, seed):
    # The POC computed: first 8 hex digits of md5("<id>:<seed>"), modulo n, plus 1.
    # Matching it exactly means the same controls get the same index dates.
    n = 4321
    expected = int(hashlib.md5(f"{patient_id}:{seed}".encode()).hexdigest()[:8], 16) % n + 1
    draw = D.random_draw("CAST(:pid AS TEXT)", seed, str(n))
    assert scalar(engine, draw, pid=patient_id) == expected


def test_text_sorts_by_byte_value_whatever_the_locale(engine):
    values = scalar(
        engine,
        "array_agg(v ORDER BY " + D.sort_key("v") + ") "
        "FROM (VALUES ('b'), ('B'), ('a'), ('A'), ('_')) t(v)",
    )
    assert values == ["A", "B", "_", "a", "b"]


def test_the_app_connection_cannot_write(engine, hand_schema):
    with engine.connect() as connection, pytest.raises(DBAPIError, match="read-only"):
        connection.execute(text(f'DELETE FROM "{hand_schema}".program_members'))


def test_query_errors_become_data_source_errors(engine):
    run = query_runner(engine)
    with pytest.raises(DataSourceError):
        run("SELECT * FROM no_such_table", {})


def test_numeric_results_come_back_as_floats_and_dates_as_timestamps(engine):
    frame = query_runner(engine)("SELECT 1.5::numeric AS n, DATE '2021-06-15' AS d", {})
    assert frame["n"].dtype == float
    assert frame["d"].iloc[0] == pd.Timestamp("2021-06-15")


# ------------------------------------------------------------------ loader


def test_loader_keeps_text_ids_and_replaces_contents(db_url, tmp_path):
    tables = {
        "master_patient": pd.DataFrame(
            {
                "patient_id": ["00123", "00456"],
                "date_of_birth": ["1950-01-01", "1960-02-02"],
                "ethnicity": ["Chinese", None],
                "gender": ["F", "M"],
                "residence_status": ["Citizen", "PR"],
                "ignored_extra_column": [1, 2],
            }
        )
    }
    schema = build_schema("loader", tables)
    with admin_connection() as conn:
        rows = conn.execute(
            f'SELECT patient_id, ethnicity FROM "{schema}".master_patient ORDER BY 1'
        ).fetchall()
        assert rows == [("00123", "Chinese"), ("00456", None)]

        # Loading again replaces rather than appends; append=True adds.
        load_tables(conn, tables, schema)
        load_tables(
            conn,
            tables | {"master_patient": tables["master_patient"].iloc[:0]},
            schema,
            append=True,
        )
        count = conn.execute(f'SELECT count(*) FROM "{schema}".master_patient').fetchone()
        assert count == (2,)


def test_loader_refuses_unknown_tables_and_missing_columns(db_url):
    schema = build_schema("loader_bad", {})
    with admin_connection() as conn:
        with pytest.raises(ValueError, match="no table"):
            load_tables(conn, {"pharmacy": pd.DataFrame()}, schema)
        with pytest.raises(ValueError, match="missing column"):
            load_tables(conn, {"program_members": pd.DataFrame({"patient_id": ["A"]})}, schema)


def test_csv_folder_is_read_as_text(tmp_path):
    (tmp_path / "program_members.csv").write_text(
        "patient_id,enrollment_date\n00123,2021-06-15\n", encoding="utf-8"
    )
    tables = read_csv_folder(tmp_path)
    assert tables["program_members"]["patient_id"].tolist() == ["00123"]


def test_apply_schema_is_idempotent(db_url):
    schema = build_schema("idempotent", {})
    with admin_connection() as conn:
        apply_schema(conn, schema)
        apply_schema(conn, schema)
