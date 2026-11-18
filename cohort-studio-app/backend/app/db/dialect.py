"""SQL fragments that differ between database engines: PostgreSQL and Databricks.

The SQL generator (queries.py) calls these instead of writing date functions
itself, so another engine needs another class with the same methods and
nothing else in the generator changes. Every method returns a piece of SQL
text. Arguments named `date`, `expr` and so on are SQL expressions built by
the generator; numeric arguments are passed through int() so nothing but a
number can reach the query that way.

No method writes a `%` or a `:name` sequence, because the query text goes
through SQLAlchemy's text(), where `:name` is a bound parameter.
"""

from typing import Protocol


class Dialect(Protocol):
    name: str

    def param(self, key: str) -> str: ...
    def text(self, expr: str) -> str: ...
    def real(self, expr: str) -> str: ...
    def add_days(self, date: str, n: int) -> str: ...
    def add_months(self, date: str, n: int) -> str: ...
    def year(self, date: str) -> str: ...
    def month_number(self, date: str) -> str: ...
    def days_between(self, start: str, end: str) -> str: ...
    def age_years(self, birth: str, at: str) -> str: ...
    def random_draw(self, expr: str, seed: int, n: str) -> str: ...
    def sort_key(self, expr: str) -> str: ...


class PostgresDialect:
    name = "postgres"

    def param(self, key: str) -> str:
        """Placeholder for a bound query parameter, in SQLAlchemy text() form."""
        return f":{key}"

    def text(self, expr: str) -> str:
        return f"CAST({expr} AS TEXT)"

    def real(self, expr: str) -> str:
        # Integer / numeric arithmetic gives NUMERIC in PostgreSQL, which the
        # driver returns as Decimal. The statistics want floats.
        return f"CAST({expr} AS DOUBLE PRECISION)"

    def add_days(self, date: str, n: int) -> str:
        # DATE + INTEGER is a DATE in PostgreSQL.
        return f"({date} + ({int(n)}))"

    def add_months(self, date: str, n: int) -> str:
        # Month ends are clamped: 31 January + 1 month is 28 or 29 February,
        # the same as DuckDB and Databricks add_months.
        return f"CAST({date} + make_interval(months => {int(n)}) AS DATE)"

    def year(self, date: str) -> str:
        return f"CAST(EXTRACT(YEAR FROM {date}) AS INTEGER)"

    def month_number(self, date: str) -> str:
        """Months since year 0, so that consecutive calendar months differ by one."""
        return (
            f"(CAST(EXTRACT(YEAR FROM {date}) AS INTEGER) * 12"
            f" + CAST(EXTRACT(MONTH FROM {date}) AS INTEGER) - 1)"
        )

    def days_between(self, start: str, end: str) -> str:
        # DATE - DATE is a whole number of days.
        return f"({end} - {start})"

    def age_years(self, birth: str, at: str) -> str:
        # Completed years: someone born on 16 June 1960 is 60 on 15 June 2021.
        return f"CAST(EXTRACT(YEAR FROM age({at}, {birth})) AS INTEGER)"

    def random_draw(self, expr: str, seed: int, n: str) -> str:
        """A whole number from 1 to n that looks random but depends only on expr and seed.

        Built from md5, which every engine implements identically: the first
        eight hex digits of md5("<expr>:<seed>") read as an unsigned number,
        modulo n, plus one. The legacy DuckDB backend computed exactly this,
        so the same patient and seed draw the same treated index date there
        and here, and cohorts match between the two.
        """
        digest = f"md5(concat({self.text(expr)}, ':', '{int(seed)}'))"
        # 'x' || 16 hex digits is a 64-bit bit string; the leading zeros keep
        # the value positive when cast to BIGINT.
        number = f"CAST(CAST('x' || lpad(substr({digest}, 1, 8), 16, '0') AS BIT(64)) AS BIGINT)"
        return f"(mod({number}, {n}) + 1)"

    def sort_key(self, expr: str) -> str:
        """Sort text by byte value, independent of the database's locale.

        Row order decides which control greedy matching picks, so it must be
        the same on every server (and the same as the legacy DuckDB backend,
        which sorts by byte value).
        """
        return f'{expr} COLLATE "C"'


class DatabricksDialect:
    """Databricks SQL (a SQL warehouse reading Unity Catalog tables).

    Every method gives the same answer as PostgresDialect for the same data,
    so a study run on the copy of the tables in Databricks picks the same
    patients, the same index dates and the same matches.
    """

    name = "databricks"

    def param(self, key: str) -> str:
        """Named parameter marker, bound by the Databricks SQL connector."""
        return f":{key}"

    def text(self, expr: str) -> str:
        return f"CAST({expr} AS STRING)"

    def real(self, expr: str) -> str:
        return f"CAST({expr} AS DOUBLE)"

    def add_days(self, date: str, n: int) -> str:
        return f"date_add({date}, {int(n)})"

    def add_months(self, date: str, n: int) -> str:
        # Clamps month ends, like PostgresDialect.add_months.
        return f"add_months({date}, {int(n)})"

    def year(self, date: str) -> str:
        return f"year({date})"

    def month_number(self, date: str) -> str:
        return f"(year({date}) * 12 + month({date}) - 1)"

    def days_between(self, start: str, end: str) -> str:
        return f"datediff({end}, {start})"

    def age_years(self, birth: str, at: str) -> str:
        # Completed years, the same as PostgreSQL's age(): a year is counted
        # once the birthday (month and day) has been reached.
        return (
            f"(year({at}) - year({birth})"
            f" - CASE WHEN month({at}) * 100 + day({at})"
            f" < month({birth}) * 100 + day({birth}) THEN 1 ELSE 0 END)"
        )

    def random_draw(self, expr: str, seed: int, n: str) -> str:
        """The same number as PostgresDialect.random_draw: md5, first 8 hex digits, mod n, + 1."""
        digest = f"md5(concat({self.text(expr)}, ':', '{int(seed)}'))"
        number = f"CAST(conv(substr({digest}, 1, 8), 16, 10) AS BIGINT)"
        return f"(pmod({number}, {n}) + 1)"

    def sort_key(self, expr: str) -> str:
        # Databricks compares strings by byte value (UTF8_BINARY) by default.
        return expr


def dialect_for(name: str) -> Dialect:
    """The dialect a mapping's backend names."""
    dialects: dict[str, Dialect] = {
        "postgres": PostgresDialect(),
        "databricks": DatabricksDialect(),
    }
    return dialects[name]
