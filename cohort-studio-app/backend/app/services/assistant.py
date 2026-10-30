"""The study assistant: turns a research question asked in plain words into a StudySpec.

The language model only translates. It reads the question, asks about what
is missing, and proposes a study as data. Every proposal goes through the
same StudySpec schema and validate_study() rules as one made in the builder,
and the model sees the issues and fixes them. It never builds the cohort or
computes anything: once the user has reviewed the study in the builder, the
/api/analysis endpoint runs it.

converse() handles one user turn and keeps nothing between turns. The page
sends the visible conversation and the current draft (the builder's study,
including any manual edits) every time.
"""

import json
from typing import Any

from pydantic import ValidationError

from app.ai.llm.base import LLMClient
from app.ai.prompt import system_prompt
from app.ai.tools import TOOLS
from app.analysis.outcome_models import implied_model
from app.analysis.validation import ValueLookup, issues_from_pydantic, validate_study
from app.core.mapping import Mapping
from app.schemas.study import StudySpec

# Model calls in one turn, including retries after a rejected proposal.
MAX_STEPS = 8


def converse(
    history: list[dict],
    draft: StudySpec | None,
    catalogue: dict,
    mapping: Mapping,
    lookup: ValueLookup,
    client: LLMClient,
) -> dict:
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
    messages: list[dict[str, Any]] = []
    for m in history:
        messages.append({"role": m["role"], "content": m["content"]})
    if draft is not None:
        note = "Current draft study:\n" + json.dumps(draft.model_dump(mode="json"))
        messages[-1] = {
            "role": "user",
            "content": [
                {"type": "text", "text": messages[-1]["content"]},
                {"type": "text", "text": note},
            ],
        }

    system = system_prompt(catalogue, lookup)
    texts = []
    questions = []
    unsupported = None
    for _ in range(MAX_STEPS):
        step = client.step(system, messages, TOOLS)
        if step.refused:
            texts = [
                "The assistant could not help with that request. Try rephrasing it as a "
                "question about the programme and an outcome in this dataset."
            ]
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
                results.append(
                    _tool_result(
                        call.id,
                        json.dumps({"accepted": proposed is not None, "issues": issues}),
                        proposed is None,
                    )
                )
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
    result: dict[str, Any] = {
        "status": "asking",
        "reply": "\n\n".join(texts),
        "questions": questions,
        "draft": None,
        "issues": [],
        "model": None,
    }
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
        result["reply"] = (
            "The study is ready to review."
            if result["status"] == "ready"
            else "Could you tell me more about the study you have in mind?"
        )
    return result


def _check_proposal(
    spec: dict, mapping: Mapping, lookup: ValueLookup
) -> tuple[StudySpec | None, list[dict]]:
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
    result: dict[str, Any] = {"type": "tool_result", "tool_use_id": call_id, "content": content}
    if error:
        result["is_error"] = True
    return result
