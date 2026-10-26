"""Create the DuckDB tables and load CSV or Parquet files into them.

    python -m cohort_studio.loader data/cohort.duckdb exports/master_patient.csv
    python -m cohort_studio.loader data/cohort.duckdb exports/            # every file in a folder

Each file goes into the table with the same name as the file (without the
extension). By default a file replaces the table's contents; --append adds
to them instead. A file that fails to load leaves its table as it was.
"""
import argparse
from pathlib import Path

import duckdb

DDL_PATH = Path(__file__).parent / "ddl.sql"
TABLES = ("master_patient", "chronic_conditions", "ed_episodes", "program_members")


def create_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DDL_PATH.read_text(encoding="utf-8"))


def load_file(con: duckdb.DuckDBPyConnection, path: str | Path, append: bool = False) -> int:
    """Load one file into the table it is named after. Returns the number of rows loaded."""
    path = Path(path)
    table = path.stem.lower()
    if table not in TABLES:
        raise ValueError(f"{path.name}: no table called '{table}' (expected one of {', '.join(TABLES)})")
    if path.suffix.lower() == ".csv":
        # Every column read as text and then cast to the table's type below.
        # Letting DuckDB guess would turn an ID like 00123 into the number 123.
        reader = "read_csv($path, header = true, all_varchar = true)"
    elif path.suffix.lower() == ".parquet":
        reader = "read_parquet($path)"
    else:
        raise ValueError(f"{path.name}: only .csv and .parquet files can be loaded")

    target = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = $table ORDER BY ordinal_position", {"table": table}).fetchall()
    found = set()
    for row in con.execute(f"DESCRIBE SELECT * FROM {reader}", {"path": str(path)}).fetchall():
        found.add(row[0].lower())
    missing = []
    for column, _ in target:
        if column not in found:
            missing.append(column)
    if missing:
        raise ValueError(f"{path.name}: missing column(s) {', '.join(missing)}")

    # Only the table's own columns are read; anything else in the file is
    # ignored. Names come from the database catalogue, not from the file.
    casts = []
    for column, data_type in target:
        casts.append(f"CAST({column} AS {data_type}) AS {column}")

    con.execute("BEGIN TRANSACTION")
    try:
        if not append:
            con.execute(f"DELETE FROM {table}")
        before = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        con.execute(f"INSERT INTO {table} SELECT {', '.join(casts)} FROM {reader}",
                    {"path": str(path)})
        after = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return after - before


def files_to_load(paths: list[str]) -> list[Path]:
    """The files named, with any folder replaced by the CSV and Parquet files in it."""
    result = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if child.suffix.lower() in (".csv", ".parquet"):
                    result.append(child)
        else:
            result.append(p)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Load CSV or Parquet files into the DuckDB database.")
    parser.add_argument("database", help="DuckDB file; created if it does not exist")
    parser.add_argument("files", nargs="+", help="files or folders to load")
    parser.add_argument("--append", action="store_true",
                        help="add to the tables instead of replacing their contents")
    args = parser.parse_args()

    Path(args.database).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.database)
    create_tables(con)
    for path in files_to_load(args.files):
        n = load_file(con, path, append=args.append)
        print(f"{path.stem.lower()}: {n} rows loaded from {path}")
    con.close()


if __name__ == "__main__":
    main()
