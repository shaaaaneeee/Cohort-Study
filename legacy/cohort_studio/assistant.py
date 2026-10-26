"""The study assistant: turns a research question asked in plain words into a StudySpec.

The language model only translates. It reads the question, asks about what
is missing, and proposes a study as data. Every proposal goes through the
same StudySpec schema and validate_study() rules as one made in the builder,
and the model sees the issues and fixes them. It never builds the cohort or
computes anything: once the user has reviewed the study in the builder, the
existing /api/analysis endpoint runs it.

converse() handles one user turn and keeps nothing between turns. The page
sends the visible conversation and the current draft every time.

Tools the model can call:
    propose_study       submit a whole study; answered with its design issues
    list_values         the values of one dimension, when the prompt lists only some
    ask_user            end the turn with questions for the user
    report_unsupported  end the turn saying the data cannot answer the question
"""
import json

from pydantic import ValidationError

from cohort_studio.features import KeepIf, StudySpec, Window
from cohort_studio.llm import LLMClient
from cohort_studio.mapping import Mapping
from cohort_studio.models import implied_model
from cohort_studio.validator import (OUTCOME_AGGREGATIONS, ValueLookup, issues_from_pydantic,
                                     validate_study)

# Model calls in one turn, including retries after a rejected proposal.
MAX_STEPS = 8
# Values of one dimension written into the prompt. Longer lists are cut and
# the model uses list_values to see the rest.
PROMPT_VALUES = 100

TOOLS = [
    {
        "name": "propose_study",
        "description": (
            "Submit the complete study definition. The reply lists design issues found by the "
            "validator. If any has level 'error' the study was not accepted: fix it and call "
            "this tool again. Warnings are shown to the user next to the result. Always submit "
            "the whole study, not just the part that changed."),
        "input_schema": StudySpec.model_json_schema(by_alias=True),
    },
    {
        "name": "list_values",
        "description": "All values of one dimension. Use source 'person' for person attributes.",
        "input_schema": {
            "type": "object",
            "properties": {"source": {"type": "string"}, "dimension": {"type": "string"}},
            "required": ["source", "dimension"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_user",
        "description": (
            "End your turn by asking the user the questions needed to complete the study. "
            "Ask only what you cannot reasonably settle yourself, at most four questions, each "
            "with a suggested default where one exists."),
        "input_schema": {
            "type": "object",
            "properties": {"questions": {"type": "array", "items": {"type": "string"},
                                         "minItems": 1, "maxItems": 4}},
            "required": ["questions"],
            "additionalProperties": False,
        },
    },
    {
        "name": "report_unsupported",
        "description": (
            "End your turn when the question needs data, a comparison or an analysis this "
            "dataset does not have. Say what is missing and, if there is one, the closest "
            "study that is possible."),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]


def system_prompt(catalogue: dict, lookup: ValueLookup) -> str:
    """The model's instructions and everything the dataset offers, from the mapping config."""
    sources = []
    for source in catalogue["sources"]:
        dimensions = []
        for d in source["dimensions"]:
            dimensions.append({**d, "values": _some_values(lookup, source["name"], d["name"])})
        sources.append({**source, "dimensions": dimensions})
    person = {}
    for attribute in catalogue["person_attributes"]:
        person[attribute] = _some_values(lookup, "person", attribute)
    data = {
        "exposures": catalogue["exposures"],
        "person_attributes": person,
        "person_covariates": catalogue["person_covariates"],
        "sources": sources,
        "aggregations": catalogue["aggregations"],
        "outcome_aggregations": sorted(OUTCOME_AGGREGATIONS),
    }
    return f"""You help health researchers set up cohort studies in cohort-studio.
The user describes a research question in plain words. You turn it into a study
definition and submit it with propose_study. You do not run the study or compute
any result: the user reviews your study in the study builder and runs it there.

How a study works here:
- The treatment group is everyone in the chosen exposure table, indexed at their
  exposure date. The comparison group is always patients who were never exposed,
  given a pseudo index date and matched 1:1 on the covariates by propensity score.
  A different comparison (another programme, a waiting list, before and after in
  the same patients) is not supported.
- Features are covariates (adjusted for), inclusion criteria (who is kept) and
  exactly one outcome. Each counts events from one source in a time window
  around the index date and summarises them with an aggregation.
- Covariate and inclusion windows must end before the index date (to <= -1).
  Outcome windows start after it (from >= 1).
- Age limits, person filters and person covariates (age and person attributes)
  are set on the study itself, not as features.
- Feature names are lower case snake_case, unique, and not one of patient_id,
  index_date, exposure, age, person_years or a person attribute. Labels are
  short and readable.

Windows:
{Window.__doc__}
Inclusion criteria use keep_if:
{KeepIf.__doc__}
How to work:
- Only use the exposures, sources, dimensions, values and measures listed below.
  If the question needs anything else, call report_unsupported. Never stand in a
  different outcome or source for the one the user asked about without asking.
- If the question leaves something open that changes the answer (which outcome,
  which follow-up period, which population), call ask_user. Settle routine
  details yourself with sensible defaults and say what you chose: a 12-month
  look-back for prior use, adjusting for age and gender, and seed 0.
- When the study is complete, call propose_study. If it comes back with errors,
  fix them and call it again. Once it is accepted, end with a short plain-language
  summary of the study and of the defaults you chose, and tell the user to review
  it in the builder before running it.
- If a draft study is given, the user is refining it: change what they ask for
  and keep the rest.

The dataset:
{json.dumps(data, indent=1, default=str)}
"""


def _some_values(lookup: ValueLookup, source: str, dimension: str) -> list[str]:
    values = lookup(source, dimension)
    if len(values) > PROMPT_VALUES:
        return values[:PROMPT_VALUES] + [f"... {len(values) - PROMPT_VALUES} more, see list_values"]
    return values


def converse(history: list[dict], draft: StudySpec | None, catalogue: dict, mapping: Mapping,
             lookup: ValueLookup, client: LLMClient) -> dict:
    """Answer the last user message in history.

    history is [{"role": "user" | "assistant", "content": text}, ...] and ends
    with the user. Returns:
        status     "ready" (draft has no design errors), "asking" or "unsupported"
        reply      what to show the user
        questions  open questions, when the model asked any
        draft      the study so far, or None
        issues     design issues in draft
        model      the model its outcome implies, once ready
    """
    messages = []
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    if draft is not None:
        note = "Current draft study:\n" + json.dumps(draft.model_dump(mode="json"))
        messages[-1] = {"role": "user", "content": [
            {"type": "text", "text": messages[-1]["content"]}, {"type": "text", "text": note}]}

    system = system_prompt(catalogue, lookup)
    texts = []
    questions = []
    unsupported = None
    for _ in range(MAX_STEPS):
        step = client.step(system, messages, TOOLS)
        if step.refused:
            texts = ["The assistant could not help with that request. Try rephrasing it as a "
                     "question about the programme and an outcome in this dataset."]
            break
        if step.text:
            texts.append(step.text)
        if not step.tool_calls:
            break

        results = []
        finished = False
        for call in step.tool_calls:
            if call.name == "ask_user":
                questions = list(call.input.get("questions", []))
                finished = True
            elif call.name == "report_unsupported":
                unsupported = call.input.get("reason", "")
                finished = True
            elif call.name == "propose_study":
                proposed, issues = _check_proposal(call.input, mapping, lookup)
                if proposed is not None:
                    draft = proposed
                results.append(_tool_result(call.id, json.dumps({
                    "accepted": proposed is not None, "issues": issues}), proposed is None))
            elif call.name == "list_values":
                try:
                    values = lookup(call.input["source"], call.input["dimension"])
                    results.append(_tool_result(call.id, json.dumps(values)))
                except (KeyError, LookupError) as e:
                    results.append(_tool_result(call.id, str(e), True))
            else:
                results.append(_tool_result(call.id, f"There is no tool called {call.name}.", True))
        if finished:
            break
        messages.append({"role": "assistant", "content": step.content})
        messages.append({"role": "user", "content": results})

    if unsupported is not None:
        texts.append(unsupported)
    result = {"status": "asking", "reply": "\n\n".join(texts), "questions": questions,
              "draft": None, "issues": [], "model": None}
    if draft is not None:
        issues = validate_study(draft, mapping, lookup)
        result["draft"] = draft.model_dump(mode="json")
        result["issues"] = issues
        if not any(i["level"] == "error" for i in issues):
            outcome = next(f for f in draft.features if f.role == "outcome")
            result["model"] = implied_model(outcome)
            if not questions and unsupported is None:
                result["status"] = "ready"
    if unsupported is not None:
        result["status"] = "unsupported"
    if not result["reply"]:
        result["reply"] = "The study is ready to review." if result["status"] == "ready" else \
            "Could you tell me more about the study you have in mind?"
    return result


def _check_proposal(spec: dict, mapping: Mapping,
                    lookup: ValueLookup) -> tuple[StudySpec | None, list[dict]]:
    """The study if it is well-formed and has no design errors, and its issues either way."""
    try:
        study = StudySpec.model_validate(spec)
    except ValidationError as e:
        return None, issues_from_pydantic(e.errors())
    issues = validate_study(study, mapping, lookup)
    if any(i["level"] == "error" for i in issues):
        return None, issues
    return study, issues


def _tool_result(call_id: str, content: str, error: bool = False) -> dict:
    result = {"type": "tool_result", "tool_use_id": call_id, "content": content}
    if error:
        result["is_error"] = True
    return result
