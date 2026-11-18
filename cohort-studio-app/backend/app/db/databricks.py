"""Running queries on a Databricks SQL warehouse instead of PostgreSQL.

Used when the mapping says `backend: dialect: databricks`, for example when
the app runs as a Databricks App next to a copy of the tables in Unity
Catalog. The query text is the same the generator writes for PostgreSQL,
with DatabricksDialect's date functions; parameters are bound by the
connector, never formatted into the text.

Credentials: inside a Databricks App the platform gives the app its own
service principal (DATABRICKS_HOST, DATABRICKS_CLIENT_ID and
DATABRICKS_CLIENT_SECRET are set for it), and databricks-sdk's Config picks
them up. Outside an App, the usual Databricks SDK variables work
(DATABRICKS_HOST with DATABRICKS_TOKEN, or a profile). Read access comes from
Unity Catalog grants: give the app's service principal SELECT on the tables
and nothing more.
"""

import logging
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

import pandas as pd

from app.core.config import Settings
from app.core.exceptions import DataSourceError
from app.db.session import QueryRunner, to_frame

log = logging.getLogger(__name__)


def _connect_factory(settings: Settings) -> Callable[[], Any]:
    """A function that opens a connection to the configured warehouse.

    Config() reads the environment (and may call the workspace), so it is made
    on the first query, not when the app starts.
    """
    warehouse = settings.databricks_warehouse_id
    timeout_s = max(1, settings.db_statement_timeout_ms // 1000)
    lock = threading.Lock()
    config: list[Any] = []

    def connect() -> Any:
        from databricks import sql
        from databricks.sdk.core import Config

        if not warehouse:
            # Raised per query, not at start-up, so the app still starts and
            # says what is missing.
            raise DataSourceError(
                "DATABRICKS_WAREHOUSE_ID is not set: the app does not know which SQL"
                " warehouse to use."
            )
        with lock:
            if not config:
                try:
                    config.append(Config())
                except ValueError as e:
                    log.exception("no Databricks credentials")
                    raise DataSourceError(
                        "No Databricks credentials: run the app as a Databricks App, or set"
                        " DATABRICKS_HOST and DATABRICKS_TOKEN."
                    ) from e
        cfg = config[0]
        host = (cfg.host or "").removeprefix("https://").removeprefix("http://").rstrip("/")
        return sql.connect(
            server_hostname=host,
            http_path=f"/sql/1.0/warehouses/{warehouse}",
            credentials_provider=lambda: cfg.authenticate,
            session_configuration={"STATEMENT_TIMEOUT": str(timeout_s)},
            user_agent_entry="cohort-studio",
        )

    return connect


def databricks_runner(settings: Settings, connect: Callable[[], Any] | None = None) -> QueryRunner:
    """Like session.query_runner, for a Databricks SQL warehouse."""
    open_connection = connect or _connect_factory(settings)

    def run(query: str, params: Mapping[str, object]) -> pd.DataFrame:
        from databricks.sql.exc import Error as DatabricksError
        from databricks.sql.exc import RequestError

        started = time.perf_counter()
        log.debug("query sql", extra={"sql": query, "param_count": len(params)})
        try:
            with open_connection() as connection, connection.cursor() as cursor:
                cursor.execute(query, dict(params))
                columns = [c[0] for c in cursor.description or []]
                rows = cursor.fetchall()
        except DataSourceError:
            raise
        except RequestError as e:
            log.exception("warehouse unavailable")
            raise DataSourceError("The SQL warehouse could not be reached.") from e
        except DatabricksError as e:
            log.exception("query failed")
            raise DataSourceError("The SQL warehouse could not run the query.") from e
        log.info(
            "query",
            extra={
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "rows": len(rows),
                "columns": len(columns),
            },
        )
        return to_frame([tuple(r) for r in rows], columns)

    return run


def databricks_ping(run: QueryRunner) -> Callable[[], None]:
    """A /health check: raise if the warehouse cannot answer SELECT 1."""

    def check() -> None:
        run("SELECT 1 AS ok", {})

    return check
