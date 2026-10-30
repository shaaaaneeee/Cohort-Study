"""The language model behind the study assistant, kept behind one small interface.

The assistant never imports a provider SDK. It talks to an LLMClient, which
takes one step of a conversation and returns what the model said and which
tools it wants to call. Messages use the Messages API shape (role, content
blocks of type text, tool_use and tool_result); another provider's client
translates to and from that shape.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


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
    def step(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Step: ...
