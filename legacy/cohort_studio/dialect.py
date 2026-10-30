"""SQL fragments that differ between database engines.

The SQL generator calls these instead of writing date functions itself, so a
new backend needs a new dialect class and nothing else in the generator
changes. Every method returns a piece of SQL text. Arguments named `date`,
`expr` and so on are SQL expressions built by the generator; numeric
arguments are passed through int() so nothing but a number can reach the
query that way.

DatabricksDialect is added with the Databricks backend.
"""


class DuckDbDialect:
    name = "duckdb"

    def param(self, key: str) -> str:
        """Placeholder for a bound query parameter."""
        return f"${key}"

    def text(self, expr: str) -> str:
        return f"CAST({expr} AS VARCHAR)"

    def add_days(self, date: str, n: int) -> str:
        # DATE + INTEGER is a DATE in DuckDB.
        return f"({date} + {int(n)})"

    def add_months(self, date: str, n: int) -> str:
        # Month ends are clamped: 31 January + 1 month is 28 or 29 February.
        # Databricks add_months does the same, so both backends agree.
        return f"CAST({date} + INTERVAL ({int(n)}) MONTH AS DATE)"

    def year(self, date: str) -> str:
        return f"year({date})"

    def month_number(self, date: str) -> str:
        """Months since year 0, so that consecutive calendar months differ by one."""
        return f"(year({date}) * 12 + month({date}) - 1)"

    def days_between(self, start: str, end: str) -> str:
        return f"date_diff('day', {start}, {end})"

    def age_years(self, birth: str, at: str) -> str:
        # Completed years: someone born on 16 June 1960 is 60 on 15 June 2021.
        # date_diff('year', ...) would count calendar-year boundaries instead
        # and make them 61.
        return f"date_sub('year', {birth}, {at})"

    def random_draw(self, expr: str, seed: int, n: str) -> str:
        """A whole number from 1 to n that looks random but depends only on expr and seed.

        Built from md5, which every engine implements identically, so the
        same patient and seed give the same draw on DuckDB and on Databricks.
        Eight hex digits give a number up to about 4.3 billion, and the
        remainder after dividing by n is close enough to uniform for any n in
        the thousands.
        """
        digest = f"md5(concat({self.text(expr)}, ':', '{int(seed)}'))"
        return f"(CAST(('0x' || substr({digest}, 1, 8)) AS BIGINT) % {n} + 1)"
