"""The Databricks SQL warehouse backend, without a warehouse.

That the Databricks SQL gives the same cohorts and results as PostgreSQL was
checked by running a full study on Spark SQL (ANSI mode) next to PostgreSQL;
these tests cover the wiring.
"""

import datetime as dt

import pytest

from app.core.config import BACKEND_DIR, Settings
from app.core.exceptions import DataSourceError
from app.core.mapping import load_mapping
from app.db.databricks import databricks_runner
from app.db.dialect import DatabricksDialect, dialect_for


class FakeCursor:
    def __init__(self, log: list):
        self.log = log
        self.description = [("patient_id",), ("index_date",), ("n",)]

    def execute(self, query, params):
        self.log.append((query, params))

    def fetchall(self):
        return [("P1", dt.date(2020, 1, 2), 3), ("P2", dt.date(2021, 5, 6), 0)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection(FakeCursor):
    def cursor(self):
        return FakeCursor(self.log)


def test_queries_bind_parameters_and_return_a_frame():
    log: list = []
    run = databricks_runner(Settings(), connect=lambda: FakeConnection(log))
    frame = run("SELECT 1 WHERE x = :p0", {"p0": "a"})
    assert log == [("SELECT 1 WHERE x = :p0", {"p0": "a"})]
    assert list(frame.columns) == ["patient_id", "index_date", "n"]
    assert str(frame["index_date"].dtype).startswith("datetime64")


def test_no_warehouse_is_a_clear_error():
    run = databricks_runner(Settings(databricks_warehouse_id=""))
    with pytest.raises(DataSourceError, match="DATABRICKS_WAREHOUSE_ID"):
        run("SELECT 1", {})


def test_the_databricks_mapping_reads_unity_catalog():
    mapping = load_mapping(BACKEND_DIR / "config" / "mapping.databricks.yaml")
    assert isinstance(dialect_for(mapping.backend.dialect), DatabricksDialect)
    assert mapping.person.table == "workspace.cohort.master_patient"


def test_random_draw_matches_postgres_arithmetic():
    sql = DatabricksDialect().random_draw("patient_id", 7, "n")
    assert sql == (
        "(pmod(CAST(conv(substr(md5(concat(CAST(patient_id AS STRING), ':', '7')), 1, 8),"
        " 16, 10) AS BIGINT), n) + 1)"
    )


def test_the_port_databricks_apps_gives_is_used(monkeypatch):
    monkeypatch.setenv("DATABRICKS_APP_PORT", "8123")
    assert Settings().port == 8123
