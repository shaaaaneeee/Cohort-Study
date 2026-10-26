"""The language model behind the study assistant, kept behind one small interface.

assistant.py never imports a provider SDK. It talks to an LLMClient, which
takes one step of a conversation and returns what the model said and which
tools it wants to call. Messages use the Messages API shape (role, content
blocks of type text, tool_use and tool_result); another provider's client
translates to and from that shape.

    COHORT_LLM=anthropic   (default) Claude, through the anthropic SDK
    COHORT_LLM=demo        the three demonstration scenarios, picked by the question
    COHORT_LLM=scripted    canned replies from one JSON file

The scripted client is also what the tests use.
"""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class Step:
    """One model response.

    content is the assistant message exactly as it came back, to be sent back
    unchanged in the next request of the same turn (the API checks that
    thinking blocks are not edited). refused is set when the model declined
    the request.
    """
    text: str
    tool_calls: list[ToolCall]
    content: Any
    refused: bool = False


class LLMError(Exception):
    """The model could not be reached: no package, no credentials, network or API failure."""


class LLMClient(Protocol):
    def step(self, system: str, messages: list[dict], tools: list[dict]) -> Step: ...


class AnthropicClient:
    """Claude through the anthropic SDK.

    Credentials come from the environment (ANTHROPIC_API_KEY or an `ant auth
    login` profile). COHORT_LLM_MODEL and COHORT_LLM_EFFORT override the model
    and effort. If a safety classifier declines a request, the API retries it
    on a fallback model it picks itself ("fallbacks": "default").
    """

    def __init__(self, model: str | None = None, effort: str | None = None):
        # Imported here so the rest of the app runs without the package.
        try:
            import anthropic
        except ImportError:
            raise LLMError("The anthropic package is not installed: pip install anthropic") from None
        self._anthropic = anthropic
        try:
            self._client = anthropic.Anthropic()
        except anthropic.AnthropicError as e:
            raise LLMError(f"Could not set up the Claude client: {e}") from None
        self.model = model or os.environ.get("COHORT_LLM_MODEL", "claude-opus-5-5")
        self.effort = effort or os.environ.get("COHORT_LLM_EFFORT", "medium")

    def step(self, system: str, messages: list[dict], tools: list[dict]) -> Step:
        anthropic = self._anthropic
        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system,
                messages=messages,
                tools=tools,
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.AuthenticationError:
            raise LLMError("Claude rejected the credentials. Set ANTHROPIC_API_KEY.") from None
        except anthropic.RateLimitError:
            raise LLMError("Claude is rate limiting requests. Try again in a minute.") from None
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude returned an error ({e.status_code}): {e.message}") from None
        except anthropic.APIConnectionError:
            raise LLMError("Could not connect to Claude. Check the internet connection.") from None
        except anthropic.AnthropicError as e:
            raise LLMError(f"Could not call Claude: {e}") from None
        except TypeError as e:
            # The SDK raises a TypeError, before sending anything, when no
            # credentials are set. Any other TypeError is a bug and goes up.
            if "authentication" not in str(e):
                raise
            raise LLMError("No Claude credentials are set. Set ANTHROPIC_API_KEY and restart "
                           "the server.") from None
        texts = []
        calls = []
        for block in response.content:
            if block.type == "text":
                texts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(block.id, block.name, block.input))
        return Step(text="\n".join(texts), tool_calls=calls, content=response.content,
                    refused=response.stop_reason == "refusal")


@dataclass
class ScriptedClient:
    """Replays a fixed list of steps, one per call, ignoring what it is sent.

    Each step is {"text": ..., "tool_calls": [{"name": ..., "input": {...}}]}.
    What it was sent is kept in `requests`, so tests can check the prompt and
    the tool results the assistant fed back.
    """
    steps: list[dict]
    requests: list[dict] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: str | Path) -> "ScriptedClient":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def step(self, system: str, messages: list[dict], tools: list[dict]) -> Step:
        self.requests.append({"system": system, "messages": list(messages), "tools": tools})
        if not self.steps:
            raise LLMError("The scripted model has no replies left. Restart the server to replay it.")
        spec = self.steps.pop(0)
        calls = []
        content = []
        if spec.get("text"):
            content.append({"type": "text", "text": spec["text"]})
        for k, call in enumerate(spec.get("tool_calls", [])):
            call_id = f"call_{len(self.requests)}_{k}"
            calls.append(ToolCall(call_id, call["name"], call["input"]))
            content.append({"type": "tool_use", "id": call_id, "name": call["name"],
                            "input": call["input"]})
        return Step(text=spec.get("text", ""), tool_calls=calls, content=content)


TERMINAL_TOOLS = {"ask_user", "report_unsupported"}
EXAMPLES = Path(__file__).parent.parent / "examples" / "assistant"


class DemoClient:
    """Plays the three demonstration scenarios, for trying the app with no key.

    The scenario is chosen from the conversation's first question: mortality,
    death or admission plays the unsupported one, "help" the ambiguous one,
    anything else the complete one. Every conversation starts the scenario
    from the beginning, so it can be replayed as often as wanted.
    """

    def __init__(self, folder: Path = EXAMPLES):
        self.scenarios = {}
        for name, file in [("complete", "scenario_a_complete.json"),
                           ("ambiguous", "scenario_b_ambiguous.json"),
                           ("unsupported", "scenario_c_unsupported.json")]:
            steps = json.loads((folder / file).read_text(encoding="utf-8"))
            self.scenarios[name] = _turns(steps)

    def step(self, system: str, messages: list[dict], tools: list[dict]) -> Step:
        question = _text(messages[0]["content"]).lower()
        if any(word in question for word in ("mortality", "death", "die", "admission")):
            turns = self.scenarios["unsupported"]
        elif "help" in question:
            turns = self.scenarios["ambiguous"]
        else:
            turns = self.scenarios["complete"]
        # Earlier turns left one plain-text reply each in the history; steps
        # taken in this turn left assistant messages made of content blocks.
        turn = sum(1 for m in messages if m["role"] == "assistant" and isinstance(m["content"], str))
        within = sum(1 for m in messages if m["role"] == "assistant" and not isinstance(m["content"], str))
        if turn >= len(turns):
            return Step(text="This is the end of the demo conversation. Click Start over to play "
                             "it again, or set ANTHROPIC_API_KEY to ask anything.",
                        tool_calls=[], content=[])
        return ScriptedClient([turns[turn][min(within, len(turns[turn]) - 1)]]).step(
            system, messages, tools)


def _turns(steps: list[dict]) -> list[list[dict]]:
    """Split a script into user turns. A turn ends at a step with no tool call or an ending one."""
    turns, current = [], []
    for step in steps:
        current.append(step)
        names = {c["name"] for c in step.get("tool_calls", [])}
        if not names or names & TERMINAL_TOOLS:
            turns.append(current)
            current = []
    if current:
        turns.append(current)
    return turns


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(block.get("text", "") for block in content if isinstance(block, dict))


def client_from_env() -> LLMClient:
    kind = os.environ.get("COHORT_LLM", "anthropic")
    if kind == "anthropic":
        return AnthropicClient()
    if kind == "demo":
        return DemoClient()
    if kind == "scripted":
        if "COHORT_LLM_SCRIPT" not in os.environ:
            raise LLMError("COHORT_LLM=scripted needs COHORT_LLM_SCRIPT, the path of a script file.")
        return ScriptedClient.from_file(os.environ["COHORT_LLM_SCRIPT"])
    raise LLMError(f"COHORT_LLM must be 'anthropic', 'demo' or 'scripted', not '{kind}'.")
