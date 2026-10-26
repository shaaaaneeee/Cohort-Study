"""Tests for creating the tables and loading CSV and Parquet files."""
from datetime import date

import duckdb
import pytest

from cohort_studio import loader


@pytest.fixture
def con(tmp_path):
    con = duckdb.connect(str(tmp_path / "load.duckdb"))
    loader.create_tables(con)
    yield con
    con.close()


def write(path, text: str):
    path.write_text(text, encoding="utf-8")
    return path


def rows(con, table: str) -> list[tuple]:
    return con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()


def test_creating_tables_twice_is_harmless(con):
    loader.create_tables(con)
    names = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    assert set(loader.TABLES) <= names


def test_csv_is_loaded_with_the_table_types(con, tmp_path):
    path = write(tmp_path / "program_members.csv",
                 "patient_id,enrollment_date\n00123,2021-06-15\n00124,2022-01-01\n")
    assert loader.load_file(con, path) == 2
    first = rows(con, "program_members")[0]
    assert first[0] == "00123"                       # leading zeros kept
    assert str(first[1]) == "2021-06-15"
    types = dict(con.execute("SELECT column_name, data_type FROM information_schema.columns "
                             "WHERE table_name = 'program_members'").fetchall())
    assert types["enrollment_date"] == "DATE"


def test_parquet_is_loaded(con, tmp_path):
    path = tmp_path / "chronic_conditions.parquet"
    con.execute(f"COPY (SELECT 'P1' AS patient_id, 'copd' AS condition_name, 2019 AS diagnosis_year) "
                f"TO '{path}' (FORMAT parquet)")
    assert loader.load_file(con, path) == 1
    assert rows(con, "chronic_conditions") == [("P1", "copd", 2019)]


def test_load_replaces_by_default_and_appends_on_request(con, tmp_path):
    path = write(tmp_path / "program_members.csv", "patient_id,enrollment_date\nP1,2021-06-15\n")
    loader.load_file(con, path)
    loader.load_file(con, path)
    assert len(rows(con, "program_members")) == 1
    loader.load_file(con, path, append=True)
    assert len(rows(con, "program_members")) == 2


def test_columns_are_matched_by_name_and_extras_ignored(con, tmp_path):
    path = write(tmp_path / "program_members.csv",
                 "Enrollment_Date,source_system,Patient_ID\n2021-06-15,X,P1\n")
    loader.load_file(con, path)
    assert rows(con, "program_members") == [("P1", date(2021, 6, 15))]


def test_missing_column_is_refused(con, tmp_path):
    path = write(tmp_path / "program_members.csv", "patient_id\nP1\n")
    with pytest.raises(ValueError, match="enrollment_date"):
        loader.load_file(con, path)


def test_bad_value_leaves_the_table_unchanged(con, tmp_path):
    good = write(tmp_path / "program_members.csv", "patient_id,enrollment_date\nP1,2021-06-15\n")
    loader.load_file(con, good)
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    bad = write(bad_dir / "program_members.csv", "patient_id,enrollment_date\nP2,not a date\n")
    with pytest.raises(duckdb.Error):
        loader.load_file(con, bad)
    assert [r[0] for r in rows(con, "program_members")] == ["P1"]


@pytest.mark.parametrize("filename", ["patients.csv", "program_members.xlsx"])
def test_unknown_table_or_format_is_refused(con, tmp_path, filename):
    path = write(tmp_path / filename, "patient_id,enrollment_date\nP1,2021-06-15\n")
    with pytest.raises(ValueError):
        loader.load_file(con, path)


def test_a_folder_expands_to_its_data_files(tmp_path):
    write(tmp_path / "master_patient.csv", "")
    write(tmp_path / "ed_episodes.parquet", "")
    write(tmp_path / "notes.txt", "")
    found = [p.name for p in loader.files_to_load([str(tmp_path)])]
    assert found == ["ed_episodes.parquet", "master_patient.csv"]
