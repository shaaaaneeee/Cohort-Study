"""Tests for the study assistant, with a scripted model in place of a real one.

The scripts in examples/assistant are the three demonstration scenarios from
the proposal; replaying them here keeps the demos working.
"""
import json
from pathlib import Path

import pytest

from cohort_studio.api import catalogue
from cohort_studio.assistant import MAX_STEPS, converse
from cohort_studio.features import StudySpec
from cohort_studio.llm import DemoClient, ScriptedClient

EXAMPLES = Path(__file__).parent.parent / "examples" / "assistant"


def script(name: str) -> list[dict]:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def ed(name: str, start: int, end: int, role: str, aggregation: str = "count") -> dict:
    return {"name": name, "label": name, "source": "ed_episodes",
            "window": {"from": start, "to": end, "unit": "months"},
            "aggregation": aggregation, "role": role}


GOOD_STUDY = {"exposure": "program_a", "person_covariates": ["age", "gender"],
              "features": [ed("prior_ed", -12, -1, "covariate"), ed("ed_after", 1, 12, "outcome")]}


def propose(study: dict, text: str = "") -> dict:
    return {"text": text, "tool_calls": [{"name": "propose_study", "input": study}]}


@pytest.fixture
def ask(synthetic_repo):
    """converse() on the synthetic data: ask(steps, question, draft=None) -> (result, client)."""
    def run(steps, question="Does Programme A reduce ED attendances?", draft=None, history=None,
            client_class=ScriptedClient):
        client = client_class(list(steps))
        messages = (history or []) + [{"role": "user", "content": question}]
        result = converse(messages, draft, catalogue(synthetic_repo.mapping),
                          synthetic_repo.mapping, synthetic_repo.dimension_values, client)
        return result, client
    return run


def last_tool_results(client: ScriptedClient, request: int) -> list[dict]:
    return json.loads(client.requests[request]["messages"][-1]["content"][0]["content"])


# ------------------------------------------------------------- scenarios

def test_scenario_a_complete_question_gives_a_ready_study(ask):
    result, _ = ask(script("scenario_a_complete.json"))
    assert result["status"] == "ready"
    study = StudySpec.model_validate(result["draft"])
    outcomes = [f.name for f in study.features if f.role == "outcome"]
    assert outcomes == ["ed_after"]
    assert not [i for i in result["issues"] if i["level"] == "error"]
    assert result["model"]["measure"] == "Rate ratio"
    assert "Review it in the builder" in result["reply"]


def test_scenario_b_ambiguous_question_asks_before_drafting(ask):
    steps = script("scenario_b_ambiguous.json")
    first, _ = ask(steps[:1], "Does Programme A help patients?")
    assert first["status"] == "asking"
    assert first["draft"] is None
    assert len(first["questions"]) == 3

    history = [{"role": "user", "content": "Does Programme A help patients?"},
               {"role": "assistant", "content": first["reply"]}]
    second, _ = ask(steps[1:], "Any ED visit, 12 months, adults with diabetes.", history=history)
    assert second["status"] == "ready"
    roles = sorted(f["role"] for f in second["draft"]["features"])
    assert roles == ["covariate", "inclusion", "outcome"]
    assert second["draft"]["age_min"] == 18
    assert second["model"]["model"] == "logistic"


def test_scenario_c_unsupported_question_is_explained_not_invented(ask):
    result, _ = ask(script("scenario_c_unsupported.json"), "Does Programme A reduce mortality?")
    assert result["status"] == "unsupported"
    assert result["draft"] is None
    assert "no hospital admission or mortality" in result["reply"]


# --------------------------------------------------------- the validator loop

def test_a_proposal_with_design_errors_is_returned_to_the_model_and_fixed(ask):
    lookahead = {**GOOD_STUDY, "features": [ed("prior_ed", -12, 0, "covariate"),
                                            ed("ed_after", 1, 12, "outcome")]}
    result, client = ask([propose(lookahead), propose(GOOD_STUDY), {"text": "Ready."}])

    feedback = client.requests[1]["messages"][-1]["content"][0]
    assert feedback["is_error"] is True
    reply = json.loads(feedback["content"])
    assert reply["accepted"] is False
    assert "covariate_lookahead" in [i["code"] for i in reply["issues"]]

    assert last_tool_results(client, 2)["accepted"] is True
    assert result["status"] == "ready"
    assert result["draft"]["features"][0]["window"]["to"] == -1


def test_a_malformed_proposal_gets_schema_errors(ask):
    bad = {**GOOD_STUDY, "features": [ed("prior_ed", -12, -1, "covariate", "median"),
                                      ed("ed_after", 1, 12, "outcome")]}
    result, client = ask([propose(bad), {"text": "I could not build that."}])
    reply = last_tool_results(client, 1)
    assert reply["accepted"] is False
    assert reply["issues"][0]["code"] == "invalid_request"
    assert "features > 0 > aggregation" in reply["issues"][0]["message"]
    assert result["status"] == "asking"
    assert result["draft"] is None


def test_a_study_without_an_outcome_is_not_ready(ask):
    no_outcome = {**GOOD_STUDY, "features": [ed("prior_ed", -12, -1, "covariate")]}
    result, client = ask([propose(no_outcome), {"text": "Which outcome?"}])
    assert "outcome_count" in [i["code"] for i in last_tool_results(client, 1)["issues"]]
    assert result["status"] == "asking"


def test_the_turn_stops_after_max_steps(ask):
    looping = {"tool_calls": [{"name": "list_values",
                               "input": {"source": "person", "dimension": "gender"}}]}
    result, client = ask([looping] * (MAX_STEPS + 3))
    assert len(client.requests) == MAX_STEPS
    assert result["status"] == "asking"


# ----------------------------------------------------------- other details

def test_the_prompt_lists_the_dataset(ask):
    _, client = ask([{"text": "Hello."}])
    system = client.requests[0]["system"]
    for expected in ["program_a", "ed_episodes", "SCDF", "diabetes", "residence_status"]:
        assert expected in system
    names = [t["name"] for t in client.requests[0]["tools"]]
    assert names == ["propose_study", "list_values", "ask_user", "report_unsupported"]


def test_list_values_answers_and_reports_unknown_dimensions(ask):
    calls = {"tool_calls": [
        {"name": "list_values", "input": {"source": "ed_episodes", "dimension": "triage_level"}},
        {"name": "list_values", "input": {"source": "ed_episodes", "dimension": "colour"}}]}
    _, client = ask([calls, {"text": "Done."}])
    results = client.requests[1]["messages"][-1]["content"]
    assert json.loads(results[0]["content"]) == ["P1", "P2", "P3", "P4"]
    assert results[1]["is_error"] is True


def test_a_draft_is_passed_to_the_model_and_kept(ask):
    draft = StudySpec.model_validate(GOOD_STUDY)
    result, client = ask([{"text": "Nothing to change."}], "Thanks", draft=draft)
    note = client.requests[0]["messages"][-1]["content"][1]["text"]
    assert note.startswith("Current draft study:")
    assert '"from": -12' in note
    assert result["status"] == "ready"
    assert result["draft"] == draft.model_dump(mode="json")


def test_questions_about_a_valid_draft_keep_it_asking(ask):
    draft = StudySpec.model_validate(GOOD_STUDY)
    steps = [{"tool_calls": [{"name": "ask_user", "input": {"questions": ["Adults only?"]}}]}]
    result, _ = ask(steps, "Restrict the population", draft=draft)
    assert result["status"] == "asking"
    assert result["draft"] is not None
    assert result["questions"] == ["Adults only?"]


class RefusingClient(ScriptedClient):
    def step(self, system, messages, tools):
        step = super().step(system, messages, tools)
        step.refused = True
        return step


def test_a_refusal_is_reported_without_a_draft(ask):
    result, _ = ask([propose(GOOD_STUDY)], client_class=RefusingClient)
    assert result["status"] == "asking"
    assert result["draft"] is None
    assert "could not help" in result["reply"]


def test_the_demo_picks_a_scenario_from_the_question_and_replays_it(synthetic_repo):
    demo = DemoClient()

    def turn(history):
        return converse(history, None, catalogue(synthetic_repo.mapping), synthetic_repo.mapping,
                        synthetic_repo.dimension_values, demo)

    for _ in range(2):
        assert turn([{"role": "user", "content": "Does Programme A cut ED visits?"}])["status"] == "ready"
    assert turn([{"role": "user", "content": "Does Programme A reduce mortality?"}])["status"] == "unsupported"

    question = {"role": "user", "content": "Does Programme A help patients?"}
    first = turn([question])
    assert first["status"] == "asking"
    second = turn([question, {"role": "assistant", "content": first["reply"]},
                   {"role": "user", "content": "Any ED visit, adults with diabetes"}])
    assert second["status"] == "ready"
    assert second["model"]["model"] == "logistic"
