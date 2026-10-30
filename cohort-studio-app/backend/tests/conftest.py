"""Shared fixtures.

Tests that use db_url (directly or through another fixture) are marked "db"
and skipped when TEST_DATABASE_URL is not set. docs/db-setup.md shows how to
start a test PostgreSQL with docker compose.
"""

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from pydantic import SecretStr
from sqlalchemy import Engine

from app.core.config import Settings
from app.core.mapping import Mapping, load_mapping
from app.db.repositories.cohort import SqlCohortRepository
from app.db.session import create_db_engine
from app.seed import synthetic
from tests.support import (
    TEST_DATABASE_URL,
    ValuesRepository,
    build_schema,
    drop_schemas,
    hand_made_tables,
    repository_for,
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "db_url" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.db)


@pytest.fixture(scope="session")
def config_path() -> Path:
    return Path(__file__).resolve().parent.parent / "config" / "mapping.yaml"


@pytest.fixture
def mapping(config_path: Path) -> Mapping:
    """The mapping shipped in config/, so the tests also prove it is valid."""
    return load_mapping(config_path)


@pytest.fixture
def values_repo(mapping: Mapping) -> ValuesRepository:
    return ValuesRepository(mapping)


# ------------------------------------------------------------------- database


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    yield TEST_DATABASE_URL
    drop_schemas()


@pytest.fixture(scope="session")
def engine(db_url: str) -> Iterator[Engine]:
    settings = Settings(_env_file=None, database_url=SecretStr(db_url))  # type: ignore[call-arg]
    engine = create_db_engine(settings, pooled=False)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def synthetic_tables() -> dict[str, pd.DataFrame]:
    return synthetic.generate(patients=5000, seed=11)


@pytest.fixture(scope="session")
def synthetic_schema(db_url: str, synthetic_tables: dict[str, pd.DataFrame]) -> str:
    return build_schema("synthetic", synthetic_tables)


@pytest.fixture(scope="session")
def hand_schema(db_url: str) -> str:
    return build_schema("hand", hand_made_tables())


@pytest.fixture
def synthetic_repo(synthetic_schema: str, mapping: Mapping, engine: Engine) -> SqlCohortRepository:
    return repository_for(synthetic_schema, mapping, engine)


@pytest.fixture
def hand_repo(hand_schema: str, mapping: Mapping, engine: Engine) -> SqlCohortRepository:
    return repository_for(hand_schema, mapping, engine)
