"""Tests for the HTTP API, through FastAPI's test client.

Routes that build a cohort run on PostgreSQL (hand-made or synthetic data).
The rest run on a repository that only knows dimension values, so they need
no database.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import app.__main__ as entrypoint
from app.ai.llm.scripted import DEMO_SCRIPTS, ScriptedClient
from app.core.config import Settings, get_settings
from app.core.exceptions import DataSourceError
from app.core.jsonsafe import clean
from app.main import create_app

EXAMPLES = DEMO_SCRIPTS


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"app_env": "test", "log_format": "text", "log_level": "WARNING"}
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[call-arg]


def make_client(
    repo: Any, llm_client: Any = None, db_check: Callable[[], None] | None = None, **overrides: Any
) -> TestClient:
    app = create_app(
        settings(**overrides),
        repository=repo,
        llm_client=llm_client,
        db_check=db_check or (lambda: None),
    )
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(hand_repo) -> TestClient:
    return make_client(hand_repo)


@pytest.fixture
def synthetic_client(synthetic_repo) -> TestClient:
    return make_client(synthetic_repo)


@pytest.fixture
def stub_client(values_repo) -> TestClient:
    return make_client(values_repo)


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


def codes(body: dict) -> list[str]:
    return [i["code"] for i in body["issues"]]


# ----------------------------------------------------------------- metadata


def test_metadata_describes_what_the_builder_can_offer(stub_client):
    response = stub_client.get("/api/metadata")
    assert response.status_code == 200
    meta = response.json()
    assert meta["exposures"] == [{"name": "program_a", "label": "Programme A"}]
    assert meta["person_covariates"] == ["age", "ethnicity", "gender", "residence_status"]
    sources = {s["name"]: s for s in meta["sources"]}
    assert sources["condition"]["label"] == "Chronic conditions"
    assert sources["condition"]["granularity"] == "year"
    ed_source = sources["ed_episodes"]
    assert [d["name"] for d in ed_source["dimensions"]] == [
        "mode_of_arrival",
        "triage_level",
        "disposition",
    ]
    assert ed_source["measures"][0]["aggregations"] == ["mean", "sum", "max"]
    assert ed_source["coverage"] == {"start": "2018-01-01", "end": "2025-12-31"}
    assert "time_to_first" in [a["name"] for a in meta["aggregations"]]
    assert meta["window_units"] == ["days", "months", "years"]


def test_metadata_does_not_reveal_physical_table_names(stub_client):
    text = stub_client.get("/api/metadata").text
    for table in ["master_patient", "chronic_conditions", "program_members", "cohort."]:
        assert table not in text


# ------------------------------------------------------------------ values


def test_dimension_values(client):
    assert client.get("/api/values/ed_episodes/mode_of_arrival").json() == ["Own transport", "SCDF"]
    assert client.get("/api/values/person/gender").json() == ["F", "M"]
    assert client.get("/api/values/condition/condition_name").json() == [
        "asthma",
        "copd",
        "diabetes",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/api/values/ed_episodes/patient_id",
        "/api/values/pharmacy/drug",
        "/api/values/person/date_of_birth",
    ],
)
def test_unknown_dimension_is_404(stub_client, path):
    response = stub_client.get(path)
    assert response.status_code == 404
    assert response.json()["message"]
    assert response.json()["issues"] == []


# ------------------------------------------------------------------- check


def test_check_names_the_model_before_anything_runs(stub_client):
    body = stub_client.post(
        "/api/study/check", json=study(ed("ed_post", 1, 365, role="outcome"))
    ).json()
    assert body["issues"] == []
    assert body["model"]["model"] == "count"
    assert body["model"]["reason"]

    periodised = ed("ed_q", 1, 24, role="outcome", periodise={"grain": "quarter", "n": 8})
    periodised["window"]["unit"] = "months"
    body = stub_client.post("/api/study/check", json=study(periodised)).json()
    assert body["model"]["model"] == "gee"


def test_check_reports_errors_without_failing(stub_client):
    response = stub_client.post("/api/study/check", json=study(ed("ed_pre", -365, 0)))
    assert response.status_code == 200
    body = response.json()
    assert "covariate_lookahead" in codes(body)
    assert "outcome_count" in codes(body)
    assert body["model"] is None


# --------------------------------------------------------------- attrition


def test_attrition_returns_steps_and_small_cell_warnings(client):
    response = client.post("/api/attrition", json=study(age_min=18))
    assert response.status_code == 200
    body = response.json()
    assert [s["step"] for s in body["steps"]] == [
        "Starting population",
        "Has a patient record",
        "Aged 18 or over at index date",
    ]
    assert body["steps"][-1] == {
        "step": "Aged 18 or over at index date",
        "treated": 2,
        "control": 1,
    }
    assert "small_cell" in codes(body)


def test_attrition_includes_design_warnings(client):
    around_index = ed("ed_around", -30, 365, role="outcome")
    body = client.post("/api/attrition", json=study(around_index)).json()
    assert "outcome_window_before_index" in codes(body)


def test_study_with_design_errors_is_422_with_every_issue(client):
    response = client.post(
        "/api/attrition", json=study(ed("ed_pre", -365, 0), exposure="program_b")
    )
    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "The study has design errors."
    assert {"covariate_lookahead", "unknown_exposure"} <= set(codes(body))


def test_malformed_request_is_422_in_the_same_shape(stub_client):
    bad = study(ed("ed_pre", -1, -365))  # window from after to
    bad["colour"] = "blue"  # unknown field
    response = stub_client.post("/api/attrition", json=bad)
    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "The request is not a valid study."
    messages = " ".join(i["message"] for i in body["issues"])
    assert "colour" in messages
    assert "features > 0 > window" in messages
    assert set(codes(body)) == {"invalid_request"}


# ----------------------------------------------------------------- preview


def test_preview_summarises_the_feature_with_its_warnings(client):
    feature = ed("ed_around", -30, 365, role="outcome")
    response = client.post("/api/preview", json={"feature": feature, "study": study()})
    assert response.status_code == 200
    body = response.json()
    assert body["feature"] == "ed_around"
    assert body["columns"][0]["treated"]["n"] == 2
    # A design warning for this feature, and small-cell warnings from its values.
    assert "outcome_window_before_index" in codes(body)
    assert "small_cell" in codes(body)


# ---------------------------------------------------------------- analysis


def synthetic_study(**overrides: Any) -> dict:
    conditions = []
    for condition in ["diabetes", "copd", "heart_failure", "ckd"]:
        conditions.append(
            {
                "name": f"dx_{condition}",
                "label": condition,
                "source": "condition",
                "filters": {"condition_name": [condition]},
                "window": {"from": -50, "to": -1, "unit": "years"},
                "aggregation": "binary",
                "role": "covariate",
            }
        )
    outcome = ed("ed_post", 1, 365, role="outcome")
    return study(*conditions, outcome, person_covariates=["age"], **overrides)


def test_analysis_runs_end_to_end(synthetic_client):
    response = synthetic_client.post("/api/analysis", json=synthetic_study())
    assert response.status_code == 200
    body = response.json()
    assert body["model"]["measure"] == "Rate ratio"
    assert 0 < body["model"]["ci_low"] < body["model"]["estimate"] < body["model"]["ci_high"]
    assert body["cohort"]["matched"] is True
    assert len(body["balance"]) == 5
    assert body["interpretation"].startswith("Rate ratio")


def test_analysis_the_data_cannot_support_is_422(synthetic_client):
    response = synthetic_client.post("/api/analysis", json=synthetic_study(age_min=120))
    assert response.status_code == 422
    body = response.json()
    assert "both groups" in body["message"]
    assert codes(body) == ["analysis_failed"]


def test_analysis_response_carries_the_plot_data(synthetic_client):
    body = synthetic_client.post("/api/analysis", json=synthetic_study()).json()
    assert set(body["plots"]) == {"propensity", "survival", "periods"}
    assert body["plots"]["propensity"]["edges"][0] == 0


# ------------------------------------------------------------ the assistant


def test_chat_drafts_a_study_the_analysis_endpoint_accepts(synthetic_repo):
    steps = json.loads((EXAMPLES / "scenario_a_complete.json").read_text(encoding="utf-8"))
    client = make_client(synthetic_repo, ScriptedClient(steps))
    question = {"role": "user", "content": "Does Programme A reduce ED attendances over 12 months?"}
    body = client.post("/api/chat", json={"messages": [question]}).json()
    assert body["status"] == "ready"
    # The draft goes to the other endpoints unchanged once the user has reviewed it.
    analysis = client.post("/api/analysis", json=body["draft"])
    assert analysis.status_code == 200
    result = analysis.json()
    assert result["model"]["measure"] == "Rate ratio"
    assert result["interpretation"]


def test_chat_sends_the_builder_study_to_the_model(values_repo):
    # Manual changes in the builder reach the model: the current study is sent with the turn.
    scripted = ScriptedClient([{"text": "Noted."}])
    client = make_client(values_repo, scripted)
    draft = study(
        ed("ed_pre", -365, -1),
        ed("ed_post", 1, 365, role="outcome"),
        age_min=40,
        person_filters={"gender": ["F"]},
    )
    body = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "Keep it as it is"}], "draft": draft},
    ).json()
    note = scripted.requests[0]["messages"][-1]["content"][1]["text"]
    assert '"age_min": 40' in note
    assert '"gender": ["F"]' in note
    assert body["status"] == "ready"
    assert body["draft"]["age_min"] == 40
    assert body["draft"]["features"][0]["window"] == {
        "anchor": "index",
        "from": -365,
        "to": -1,
        "unit": "days",
    }


def test_chat_refuses_a_conversation_that_does_not_end_with_the_user(values_repo):
    client = make_client(values_repo, ScriptedClient([]))
    body = {
        "messages": [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    }
    response = client.post("/api/chat", json=body)
    assert response.status_code == 422
    assert codes(response.json()) == ["invalid_request"]


def test_chat_reports_an_unreachable_model_as_503(values_repo):
    client = make_client(values_repo, ScriptedClient([]))
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "Hi"}]})
    assert response.status_code == 503
    assert codes(response.json()) == ["assistant_unavailable"]


def test_chat_model_comes_from_the_settings(values_repo):
    client = make_client(
        values_repo, llm_provider="scripted", llm_script=EXAMPLES / "scenario_c_unsupported.json"
    )
    body = client.post(
        "/api/chat", json={"messages": [{"role": "user", "content": "Mortality?"}]}
    ).json()
    assert body["status"] == "unsupported"


def test_without_a_key_the_assistant_plays_the_demo(values_repo):
    client = make_client(values_repo)  # no LLM_API_KEY, no LLM_PROVIDER
    question = {"role": "user", "content": "Does Programme A reduce ED attendances?"}
    body = client.post("/api/chat", json={"messages": [question]}).json()
    assert body["status"] == "ready"
    assert body["draft"]["exposure"] == "program_a"


def test_with_a_key_the_provider_is_anthropic():
    assert settings(llm_api_key=SecretStr("k")).resolved_llm_provider == "anthropic"
    assert settings().resolved_llm_provider == "demo"
    assert settings(llm_api_key=SecretStr("k"), llm_provider="demo").resolved_llm_provider == "demo"


# ----------------------------------------------------- health and operations


def test_health_checks_the_database(values_repo):
    assert make_client(values_repo).get("/health").json()["status"] == "ok"

    def down() -> None:
        raise DataSourceError("no database")

    response = make_client(values_repo, db_check=down).get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_health_against_postgres(engine, hand_repo):
    from app.db.session import ping

    client = make_client(hand_repo, db_check=lambda: ping(engine))
    assert client.get("/health").json() == {"status": "ok", "database": "ok", "version": "1.0.0"}


def test_a_database_failure_is_503_in_the_usual_shape(values_repo):
    class Broken(type(values_repo)):  # type: ignore[misc]
        def attrition_counts(self, spec: object) -> list[dict]:
            raise DataSourceError("The database could not be reached.")

    client = make_client(Broken(values_repo.mapping))
    response = client.post("/api/attrition", json=study())
    assert response.status_code == 503
    assert codes(response.json()) == ["database_unavailable"]


def test_an_unexpected_error_is_500_without_details(values_repo):
    class Broken(type(values_repo)):  # type: ignore[misc]
        def attrition_counts(self, spec: object) -> list[dict]:
            raise RuntimeError("secret internals")

    response = make_client(Broken(values_repo.mapping)).post("/api/attrition", json=study())
    assert response.status_code == 500
    assert "secret" not in response.text
    assert response.json() == {"message": "Something went wrong on the server.", "issues": []}


def test_unknown_paths_are_404_in_the_usual_shape(stub_client):
    response = stub_client.get("/api/nothing-here")
    assert response.status_code == 404
    assert set(response.json()) == {"message", "issues"}


def test_cors_allows_only_the_configured_frontend(values_repo):
    client = make_client(values_repo, cors_origins="https://studio.example.org")
    preflight = {
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    allowed = client.options(
        "/api/study/check", headers={"Origin": "https://studio.example.org", **preflight}
    )
    assert allowed.headers["access-control-allow-origin"] == "https://studio.example.org"
    other = client.options(
        "/api/study/check", headers={"Origin": "https://evil.example.com", **preflight}
    )
    assert "access-control-allow-origin" not in other.headers


def test_cors_origins_are_read_as_a_comma_separated_list(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://a.example.org/")
    assert Settings(_env_file=None).cors_origins == [  # type: ignore[call-arg]
        "http://localhost:5173",
        "https://a.example.org",
    ]


def test_api_key_is_required_when_configured(values_repo):
    client = make_client(values_repo, api_key=SecretStr("s3cret"))
    assert client.get("/api/metadata").status_code == 401
    assert client.get("/api/metadata", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/metadata", headers={"X-API-Key": "s3cret"}).status_code == 200
    # Health checks never need it.
    assert client.get("/health").status_code == 200


def test_every_response_carries_a_request_id(stub_client):
    response = stub_client.get("/api/metadata", headers={"X-Request-ID": "abc123"})
    assert response.headers["x-request-id"] == "abc123"
    assert stub_client.get("/api/metadata").headers["x-request-id"]


def test_clean_replaces_values_json_cannot_carry():
    value = {"a": float("nan"), "b": [1.0, float("inf"), {"c": -float("inf")}], "d": "x"}
    assert clean(value) == {"a": None, "b": [1.0, None, {"c": None}], "d": "x"}


def test_server_listens_on_host_and_port_from_the_environment(monkeypatch):
    started = {}
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setenv("HOST", "127.0.0.1")
    get_settings.cache_clear()
    monkeypatch.setattr(
        entrypoint.uvicorn, "run", lambda app, **kwargs: started.update(app=app, **kwargs)
    )
    try:
        entrypoint.main()
    finally:
        get_settings.cache_clear()
    assert started["host"] == "127.0.0.1"
    assert started["port"] == 9123
    assert started["factory"] is True
