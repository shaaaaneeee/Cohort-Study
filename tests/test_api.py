"""Tests for the HTTP API, through FastAPI's test client."""
import pytest
from fastapi.testclient import TestClient

from cohort_studio import api
from tests.support import build_database, hand_made_tables, repository_for


@pytest.fixture
def client(tmp_path, mapping) -> TestClient:
    path = tmp_path / "hand.duckdb"
    build_database(path, hand_made_tables())
    repo = repository_for(path, mapping)
    return TestClient(api.create_app(repo, repo.mapping))


@pytest.fixture
def synthetic_client(synthetic_db, mapping) -> TestClient:
    repo = repository_for(synthetic_db, mapping)
    return TestClient(api.create_app(repo, repo.mapping))


def ed(name: str, start: int, end: int, role: str = "covariate", **extra) -> dict:
    spec = {"name": name, "label": name, "source": "ed_episodes",
            "window": {"from": start, "to": end, "unit": "days"},
            "aggregation": "count", "role": role}
    spec.update(extra)
    return spec


def study(*features: dict, **overrides) -> dict:
    body = {"exposure": "program_a", "features": list(features)}
    body.update(overrides)
    return body


def codes(body: dict) -> list[str]:
    return [i["code"] for i in body["issues"]]


# ----------------------------------------------------------------- metadata

def test_metadata_describes_what_the_builder_can_offer(client):
    response = client.get("/api/metadata")
    assert response.status_code == 200
    meta = response.json()
    assert meta["exposures"] == [{"name": "program_a", "label": "Programme A"}]
    assert meta["person_covariates"] == ["age", "ethnicity", "gender", "residence_status"]
    sources = {s["name"]: s for s in meta["sources"]}
    assert sources["condition"]["label"] == "Chronic conditions"
    assert sources["condition"]["granularity"] == "year"
    ed_source = sources["ed_episodes"]
    assert [d["name"] for d in ed_source["dimensions"]] == ["mode_of_arrival", "triage_level", "disposition"]
    assert ed_source["measures"][0]["aggregations"] == ["mean", "sum", "max"]
    assert ed_source["coverage"] == {"start": "2018-01-01", "end": "2025-12-31"}
    assert "time_to_first" in [a["name"] for a in meta["aggregations"]]
    assert meta["window_units"] == ["days", "months", "years"]


def test_metadata_does_not_reveal_physical_table_names(client):
    text = client.get("/api/metadata").text
    for table in ["master_patient", "chronic_conditions", "program_members"]:
        assert table not in text


# ------------------------------------------------------------------ values

def test_dimension_values(client):
    assert client.get("/api/values/ed_episodes/mode_of_arrival").json() == ["Own transport", "SCDF"]
    assert client.get("/api/values/person/gender").json() == ["F", "M"]
    assert client.get("/api/values/condition/condition_name").json() == ["asthma", "copd", "diabetes"]


@pytest.mark.parametrize("path", ["/api/values/ed_episodes/patient_id",
                                  "/api/values/pharmacy/drug",
                                  "/api/values/person/date_of_birth"])
def test_unknown_dimension_is_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json()["message"]


# ------------------------------------------------------------------- check

def test_check_names_the_model_before_anything_runs(client):
    body = client.post("/api/study/check", json=study(ed("ed_post", 1, 365, role="outcome"))).json()
    assert body["issues"] == []
    assert body["model"]["model"] == "count"
    assert body["model"]["reason"]

    periodised = ed("ed_q", 1, 24, role="outcome", periodise={"grain": "quarter", "n": 8})
    periodised["window"]["unit"] = "months"
    body = client.post("/api/study/check", json=study(periodised)).json()
    assert body["model"]["model"] == "gee"


def test_check_reports_errors_without_failing(client):
    response = client.post("/api/study/check", json=study(ed("ed_pre", -365, 0)))
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
        "Starting population", "Has a patient record", "Aged 18 or over at index date"]
    assert body["steps"][-1] == {"step": "Aged 18 or over at index date", "treated": 2, "control": 1}
    assert "small_cell" in codes(body)


def test_attrition_includes_design_warnings(client):
    around_index = ed("ed_around", -30, 365, role="outcome")
    body = client.post("/api/attrition", json=study(around_index)).json()
    assert "outcome_window_before_index" in codes(body)


def test_study_with_design_errors_is_422_with_every_issue(client):
    response = client.post("/api/attrition", json=study(ed("ed_pre", -365, 0), exposure="program_b"))
    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "The study has design errors."
    assert {"covariate_lookahead", "unknown_exposure"} <= set(codes(body))


def test_malformed_request_is_422_in_the_same_shape(client):
    bad = study(ed("ed_pre", -1, -365))          # window from after to
    bad["colour"] = "blue"                      # unknown field
    response = client.post("/api/attrition", json=bad)
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

def synthetic_study(**overrides) -> dict:
    conditions = []
    for condition in ["diabetes", "copd", "heart_failure", "ckd"]:
        conditions.append({"name": f"dx_{condition}", "label": condition, "source": "condition",
                           "filters": {"condition_name": [condition]},
                           "window": {"from": -50, "to": -1, "unit": "years"},
                           "aggregation": "binary", "role": "covariate"})
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


# -------------------------------------------------------------- the rest

def test_clean_replaces_values_json_cannot_carry():
    value = {"a": float("nan"), "b": [1.0, float("inf"), {"c": -float("inf")}], "d": "x"}
    assert api.clean(value) == {"a": None, "b": [1.0, None, {"c": None}], "d": "x"}


def test_server_listens_on_this_computer_only_on_port_from_the_environment(monkeypatch):
    started = {}
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setattr(api, "open_repository", lambda mapping: None)
    monkeypatch.setattr(api.uvicorn, "run", lambda app, host, port: started.update(host=host, port=port))
    api.main()
    assert started == {"host": "127.0.0.1", "port": 9123}


# ------------------------------------------------------------ the pages

def test_the_study_builder_pages_are_served(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "<title>cohort-studio</title>" in page.text
    for path in ["/app.js", "/results.js", "/dom.js", "/style.css"]:
        assert client.get(path).status_code == 200, path
    # The pages do not hide the API.
    assert client.get("/api/metadata").status_code == 200


def test_analysis_response_carries_the_plot_data(synthetic_client):
    body = synthetic_client.post("/api/analysis", json=synthetic_study()).json()
    assert set(body["plots"]) == {"propensity", "survival", "periods"}
    assert body["plots"]["propensity"]["edges"][0] == 0
