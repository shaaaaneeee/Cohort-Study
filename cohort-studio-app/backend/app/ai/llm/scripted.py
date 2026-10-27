"""Stand-ins for the model: canned replies for tests, and the demo for running with no key."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ai.llm.base import LLMError, Step, ToolCall

TERMINAL_TOOLS = {"ask_user", "report_unsupported"}
DEMO_SCRIPTS = Path(__file__).resolve().parent.parent / "demo"


@dataclass
class ScriptedClient:
    """Replays a fixed list of steps, one per call, ignoring what it is sent.

    Each step is {"text": ..., "tool_calls": [{"name": ..., "input": {...}}]}.
    What it was sent is kept in `requests`, so tests can check the prompt and
    the tool results the assistant fed back.
    """

    steps: list[dict[str, Any]]
    requests: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path) -> "ScriptedClient":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def step(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Step:
        self.requests.append({"system": system, "messages": list(messages), "tools": tools})
        if not self.steps:
            raise LLMError(
                "The scripted model has no replies left. Restart the server to replay it."
            )
        spec = self.steps.pop(0)
        calls = []
        content: list[dict[str, Any]] = []
        if spec.get("text"):
            content.append({"type": "text", "text": spec["text"]})
        for k, call in enumerate(spec.get("tool_calls", [])):
            call_id = f"call_{len(self.requests)}_{k}"
            calls.append(ToolCall(call_id, call["name"], call["input"]))
            content.append(
                {"type": "tool_use", "id": call_id, "name": call["name"], "input": call["input"]}
            )
        return Step(text=spec.get("text", ""), tool_calls=calls, content=content)


class DemoClient:
    """Plays the three demonstration scenarios, for trying the app with no key.

    The scenario is chosen from the conversation's first question: mortality,
    death or admission plays the unsupported one, "help" the ambiguous one,
    anything else the complete one. Every conversation starts the scenario
    from the beginning, so it can be replayed as often as wanted.
    """

    def __init__(self, folder: Path = DEMO_SCRIPTS):
        self.scenarios = {}
        for name, file in [
            ("complete", "scenario_a_complete.json"),
            ("ambiguous", "scenario_b_ambiguous.json"),
            ("unsupported", "scenario_c_unsupported.json"),
        ]:
            steps = json.loads((folder / file).read_text(encoding="utf-8"))
            self.scenarios[name] = _turns(steps)

    def step(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Step:
        question = _text(messages[0]["content"]).lower()
        if any(word in question for word in ("mortality", "death", "die", "admission")):
            turns = self.scenarios["unsupported"]
        elif "help" in question:
            turns = self.scenarios["ambiguous"]
        else:
            turns = self.scenarios["complete"]
        # Earlier turns left one plain-text reply each in the history; steps
        # taken in this turn left assistant messages made of content blocks.
        turn = sum(
            1 for m in messages if m["role"] == "assistant" and isinstance(m["content"], str)
        )
        within = sum(
            1 for m in messages if m["role"] == "assistant" and not isinstance(m["content"], str)
        )
        if turn >= len(turns):
            return Step(
                text="This is the end of the demo conversation. Click Start over to "
                "play it again, or set LLM_API_KEY to ask anything.",
                tool_calls=[],
                content=[],
            )
        return ScriptedClient([turns[turn][min(within, len(turns[turn]) - 1)]]).step(
            system, messages, tools
        )


def _turns(steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Split a script into user turns. A turn ends at a step with no tool call or an ending one."""
    turns: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for step in steps:
        current.append(step)
        names = {c["name"] for c in step.get("tool_calls", [])}
        if not names or names & TERMINAL_TOOLS:
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


def _text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""
