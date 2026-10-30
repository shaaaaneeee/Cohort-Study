"""The PostgreSQL dialect's SQL fragments. Their results are checked on a real
database in tests/integration/test_dialect_db.py."""

import pytest

from app.db.dialect import PostgresDialect

D = PostgresDialect()


def test_numbers_are_forced_to_integers():
    assert D.add_days("d", -365) == "(d + (-365))"
    with pytest.raises(ValueError):
        D.add_days("d", "1; DROP TABLE x")  # type: ignore[arg-type]
    assert D.add_months("d", 3) == "CAST(d + make_interval(months => 3) AS DATE)"


def test_the_seed_is_an_integer_literal_in_the_draw():
    draw = D.random_draw("p.patient_id", 42, "n.n")
    assert "':', '42'" in draw
    assert draw.startswith("(mod(")
    with pytest.raises(ValueError):
        D.random_draw("p.patient_id", "0'; --", "n.n")  # type: ignore[arg-type]


def test_parameters_use_sqlalchemy_names():
    assert D.param("p1") == ":p1"
