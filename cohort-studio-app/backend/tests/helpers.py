"""Helpers for the MCP server tests: an app around a test repository, and example studies."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"app_env": "test", "log_format": "text", "log_level": "WARNING"}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def make_client(
    repo: Any, db_check: Callable[[], None] | None = None, **overrides: Any
) -> TestClient:
    app = create_app(settings(**overrides), repository=repo, db_check=db_check or (lambda: None))
    return TestClient(app, raise_server_exceptions=False)


def ed(name: str, start: int, end: int, role: str = "covariate", **extra: Any) -> dict:
    spec = {
        "name": name,
        "label": name,
        "source": "ed_episodes",
        "window": {"from": start, "to": end, "unit": "days"},
        "aggregation": "count",
        "role": role,
    }
    spec.update(extra)
    return spec


def study(*features: dict, **overrides: Any) -> dict:
    body: dict[str, Any] = {"exposure": "program_a", "features": list(features)}
    body.update(overrides)
    return body


def synthetic_study(**overrides: Any) -> dict:
    conditions = [
        {
            "name": f"dx_{condition}",
            "label": condition,
            "source": "condition",
            "filters": {"condition_name": [condition]},
            "window": {"from": -50, "to": -1, "unit": "years"},
            "aggregation": "binary",
            "role": "covariate",
        }
        for condition in ["diabetes", "copd", "heart_failure", "ckd"]
    ]
    outcome = ed("ed_post", 1, 365, role="outcome")
    return study(*conditions, outcome, person_covariates=["age"], **overrides)
