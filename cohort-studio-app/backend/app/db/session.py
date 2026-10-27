"""The database engine and the function that runs one query.

The app only reads. Every connection is opened with
default_transaction_read_only, so even a generated query with a mistake in it
cannot change data, whatever the database user is allowed to do. The app's
database user should still be a dedicated role with SELECT only; see
docs/db-setup.md.
"""

import datetime as dt
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.exceptions import DataSourceError

log = logging.getLogger(__name__)

# Runs one query with its bound parameters and returns the result.
QueryRunner = Callable[[str, Mapping[str, object]], pd.DataFrame]


def database_url(settings: Settings) -> URL:
    """The SQLAlchemy URL, from DATABASE_URL or from the separate DB_* settings."""
    if settings.database_url is not None:
        url = make_url(settings.database_url.get_secret_value())
        # Accept the usual postgres:// and postgresql:// forms and use psycopg 3.
        if url.drivername in ("postgres", "postgresql"):
            url = url.set(drivername="postgresql+psycopg")
        return url
    query = {}
    if settings.db_sslmode:
        query["sslmode"] = settings.db_sslmode
    return URL.create(
        "postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value() if settings.db_password else None,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        query=query,
    )


def create_db_engine(settings: Settings, read_only: bool = True, pooled: bool = True) -> Engine:
    """An engine, pooled unless pooled=False. Nothing connects until the first query.

    Tests use pooled=False so no idle connection is held between queries.
    """
    options = [f"-c statement_timeout={int(settings.db_statement_timeout_ms)}"]
    if read_only:
        options.append("-c default_transaction_read_only=on")
    connect_args = {"options": " ".join(options), "application_name": "cohort-studio-api"}
    if not pooled:
        return create_engine(database_url(settings), poolclass=NullPool, connect_args=connect_args)
    return create_engine(
        database_url(settings),
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
    )


def query_runner(engine: Engine) -> QueryRunner:
    """A function that runs a query with bound parameters and returns a DataFrame.

    Parameters are always bound by the driver, never formatted into the text.
    """

    def run(query: str, params: Mapping[str, object]) -> pd.DataFrame:
        try:
            with engine.connect() as connection:
                result = connection.execute(text(query), dict(params))
                columns = list(result.keys())
                rows = result.fetchall()
        except OperationalError as e:
            log.exception("database unavailable")
            raise DataSourceError("The database could not be reached.") from e
        except DBAPIError as e:
            log.exception("query failed")
            raise DataSourceError("The database could not run the query.") from e
        return to_frame(rows, columns)

    return run


def to_frame(rows: Sequence[Any], columns: list[str]) -> pd.DataFrame:
    """Rows as a DataFrame with the dtypes the statistics expect.

    NUMERIC values come back from psycopg as Decimal and are turned into
    floats; DATE columns become datetime64, as the analysis and the tests
    compare them with pandas Timestamps.
    """
    frame = pd.DataFrame.from_records(rows, columns=columns, coerce_float=True)
    for column in frame.columns:
        if frame[column].dtype == object:
            present = frame[column].dropna()
            if len(present) and all(
                isinstance(v, dt.date) and not isinstance(v, dt.datetime) for v in present
            ):
                frame[column] = pd.to_datetime(frame[column])
    return frame


def ping(engine: Engine) -> None:
    """Raise if the database cannot answer SELECT 1."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
