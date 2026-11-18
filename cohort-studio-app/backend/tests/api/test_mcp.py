"""The /mcp endpoint: the study tools served to AI assistants such as Genie Code."""

import json
from typing import Any

from fastapi.testclient import TestClient

from tests.api.test_api import make_client, synthetic_study

TOKEN = "test-mcp-token"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def rpc(client: TestClient, method: str, params: dict | None = None, headers=None) -> Any:
    response = client.post(
        "/mcp/",
        headers=headers or HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )
    return response


def initialize(client: TestClient) -> None:
    response = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert response.status_code == 200, response.text


def call(client: TestClient, tool: str, arguments: dict) -> dict:
    response = rpc(client, "tools/call", {"name": tool, "arguments": arguments})
    assert response.status_code == 200, response.text
    content = response.json()["result"]["content"]
    return json.loads(content[0]["text"])


def test_no_endpoint_without_a_token(synthetic_repo):
    with make_client(synthetic_repo) as client:
        assert rpc(client, "tools/list").status_code == 404


def test_a_request_without_the_token_is_refused(synthetic_repo):
    with make_client(synthetic_repo, mcp_token=TOKEN) as client:
        wrong = {**HEADERS, "Authorization": "Bearer nope"}
        assert rpc(client, "tools/list", headers=wrong).status_code == 401


def test_the_tools_are_listed(synthetic_repo):
    with make_client(synthetic_repo, mcp_token=TOKEN) as client:
        initialize(client)
        tools = rpc(client, "tools/list").json()["result"]["tools"]
        assert {t["name"] for t in tools} == {
            "describe_data",
            "list_values",
            "check_study",
            "run_study",
        }


def test_the_tools_answer_like_the_app(synthetic_repo):
    with make_client(synthetic_repo, mcp_token=TOKEN) as client:
        initialize(client)
        assert "study_schema" in call(client, "describe_data", {})
        values = call(client, "list_values", {"source": "ed_episodes", "dimension": "triage_level"})
        assert values["values"] == ["P1", "P2", "P3", "P4"]
        assert call(client, "list_values", {"source": "nope", "dimension": "x"})["ok"] is False

        checked = call(client, "check_study", {"study": synthetic_study()})
        assert checked["ok"] is True
        assert checked["attrition"]["steps"]

        result = call(client, "run_study", {"study": synthetic_study()})
        assert result["ok"] is True
        assert "estimate" in json.dumps(result)


def test_a_bad_study_comes_back_as_issues(synthetic_repo):
    with make_client(synthetic_repo, mcp_token=TOKEN) as client:
        initialize(client)
        bad = call(client, "check_study", {"study": {"exposure": "no_such_programme"}})
        assert bad["ok"] is False
        assert bad["issues"]


def test_behind_databricks_apps_no_token_is_needed(synthetic_repo):
    # Databricks Apps signs every caller in before the request reaches the app.
    plain = {k: v for k, v in HEADERS.items() if k != "Authorization"}
    with make_client(synthetic_repo, mcp_platform_auth=True) as client:
        initialize(client)
        tools = rpc(client, "tools/list", headers=plain).json()["result"]["tools"]
        assert len(tools) == 4


def test_the_url_without_a_trailing_slash_works(synthetic_repo):
    with make_client(synthetic_repo, mcp_token=TOKEN) as client:
        response = client.post(
            "/mcp",
            headers=HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            follow_redirects=False,
        )
        assert response.status_code == 200, response.text
