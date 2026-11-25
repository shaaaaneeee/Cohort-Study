"""The engine-specific SQL fragments: Databricks SQL.

The SQL generator (queries.py) calls these instead of writing date functions
itself, so another engine would need another class with the same methods and
nothing else in the generator would change. Every method returns a piece of SQL
text. Arguments named `date`, `expr` and so on are SQL expressions built by
the generator; numeric arguments are passed through int() so nothing but a
number can reach the query that way.

No method writes a `:name` sequence, because in the query text `:name` is a
parameter bound by the Databricks SQL connector.
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


class DatabricksDialect:
    """Databricks SQL (a SQL warehouse reading Unity Catalog tables).

    Row order and the random draw are deterministic, so the same data and
    seed always pick the same patients, index dates and matches.
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
        # Month ends are clamped: 31 January + 1 month is 28 or 29 February.
        return f"add_months({date}, {int(n)})"

    def year(self, date: str) -> str:
        return f"year({date})"

    def month_number(self, date: str) -> str:
        return f"(year({date}) * 12 + month({date}) - 1)"

    def days_between(self, start: str, end: str) -> str:
        return f"datediff({end}, {start})"

    def age_years(self, birth: str, at: str) -> str:
        # Completed years: a year is counted once the birthday (month and
        # day) has been reached.
        return (
            f"(year({at}) - year({birth})"
            f" - CASE WHEN month({at}) * 100 + day({at})"
            f" < month({birth}) * 100 + day({birth}) THEN 1 ELSE 0 END)"
        )

    def random_draw(self, expr: str, seed: int, n: str) -> str:
        """A whole number from 1 to n that looks random but depends only on expr and seed.

        The first eight hex digits of md5("<expr>:<seed>") read as an unsigned
        number, modulo n, plus one.
        """
        digest = f"md5(concat({self.text(expr)}, ':', '{int(seed)}'))"
        number = f"CAST(conv(substr({digest}, 1, 8), 16, 10) AS BIGINT)"
        return f"(pmod({number}, {n}) + 1)"

    def sort_key(self, expr: str) -> str:
        # Databricks compares strings by byte value (UTF8_BINARY) by default.
        return expr


def dialect_for(name: str) -> Dialect:
    """The dialect a mapping's backend names."""
    dialects: dict[str, Dialect] = {
        "databricks": DatabricksDialect(),
    }
    return dialects[name]
