"""SQL fragments that differ between database engines, for PostgreSQL.

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
