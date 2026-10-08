"""Shared fixtures."""
from pathlib import Path

import pandas as pd
import pytest

from cohort_studio import synthetic
from cohort_studio.mapping import Mapping, load_mapping
from cohort_studio.repository import SqlRepository
from tests.support import build_database, repository_for


@pytest.fixture(scope="session")
def config_path() -> Path:
    return Path(__file__).parent.parent / "config" / "mapping.yaml"


@pytest.fixture
def mapping(config_path) -> Mapping:
    """The example mapping shipped in config/, so the tests also prove it is valid."""
    return load_mapping(config_path)


@pytest.fixture(scope="session")
def synthetic_tables() -> dict[str, pd.DataFrame]:
    return synthetic.generate(patients=5000, seed=11)


@pytest.fixture(scope="session")
def synthetic_db(tmp_path_factory, synthetic_tables) -> Path:
    path = tmp_path_factory.mktemp("synthetic") / "cohort.duckdb"
    build_database(path, synthetic_tables)
    return path


@pytest.fixture
def synthetic_repo(synthetic_db, mapping) -> SqlRepository:
    return repository_for(synthetic_db, mapping)
