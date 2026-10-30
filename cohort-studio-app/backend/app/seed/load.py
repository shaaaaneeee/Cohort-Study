"""Create the cohort tables in PostgreSQL and load data into them.

This replaces the POC's DuckDB loader. It connects as a role that may write
(the database owner), never as the app's read-only role. Values are sent with
COPY, as data; table and schema names are quoted by psycopg.sql.
"""

import math
from collections.abc import Iterable
from pathlib import Path

import pandas as pd
import psycopg
from psycopg import sql

SCHEMA_SQL = Path(__file__).resolve().parent.parent.parent / "db" / "schema.sql"
TABLES = ("master_patient", "chronic_conditions", "ed_episodes", "program_members")


def connect(url: str) -> psycopg.Connection:
    """A psycopg connection from a postgres:// URL (a SQLAlchemy +psycopg URL also works)."""
    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1))


def apply_schema(conn: psycopg.Connection, schema: str) -> None:
    """Create the schema and its tables if they do not exist."""
    with conn.transaction():
        conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
        conn.execute(SCHEMA_SQL.read_text(encoding="utf-8").encode())


def is_empty(conn: psycopg.Connection, schema: str) -> bool:
    query = sql.SQL("SELECT NOT EXISTS (SELECT 1 FROM {}.master_patient)").format(
        sql.Identifier(schema)
    )
    row = conn.execute(query).fetchone()
    return bool(row and row[0])


def load_tables(
    conn: psycopg.Connection, tables: dict[str, pd.DataFrame], schema: str, append: bool = False
) -> dict[str, int]:
    """Load DataFrames into the tables they are keyed by, in one transaction.

    By default a table's contents are replaced; append=True adds to them.
    Only the table's own columns are read from each frame, and every value
    is sent as text for PostgreSQL to parse into the column's type, so an
    ID like 00123 keeps its leading zeros. Returns the rows loaded per table.
    """
    loaded = {}
    with conn.transaction():
        for table, frame in tables.items():
            if table not in TABLES:
                raise ValueError(f"no table called {table!r} (expected one of {', '.join(TABLES)})")
            target = sql.Identifier(schema, table)
            columns = _columns(conn, schema, table)
            missing = [c for c in columns if c not in frame.columns]
            if missing:
                raise ValueError(f"{table}: missing column(s) {', '.join(missing)}")
            if not append:
                conn.execute(sql.SQL("TRUNCATE {}").format(target))
            copy = sql.SQL("COPY {} ({}) FROM STDIN").format(
                target, sql.SQL(", ").join(sql.Identifier(c) for c in columns)
            )
            with conn.cursor().copy(copy) as writer:
                for row in _text_rows(frame[columns]):
                    writer.write_row(row)
            loaded[table] = len(frame)
    return loaded


def read_csv_folder(folder: Path) -> dict[str, pd.DataFrame]:
    """Every <table>.csv in a folder, read as text so IDs keep their leading zeros."""
    tables = {}
    for path in sorted(folder.glob("*.csv")):
        table = path.stem.lower()
        if table not in TABLES:
            raise ValueError(f"{path.name}: no table called {table!r}")
        tables[table] = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
    return tables


def _columns(conn: psycopg.Connection, schema: str, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, table),
    ).fetchall()
    if not rows:
        raise ValueError(f"table {schema}.{table} does not exist; apply the schema first")
    return [r[0] for r in rows]


def _text_rows(frame: pd.DataFrame) -> Iterable[list[str | None]]:
    for values in frame.itertuples(index=False, name=None):
        yield [_text(v) for v in values]


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if value is pd.NaT:
        return None
    return str(value)
