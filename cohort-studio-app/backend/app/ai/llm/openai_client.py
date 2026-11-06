"""Any model behind an OpenAI-compatible API (Chat Completions), through the openai SDK.

Used for the approved government LLM gateway: the key, base URL and model come
from LLM_API_KEY, LLM_BASE_URL and LLM_MODEL. The assistant speaks the Messages
API shape (see base.py); this client translates to Chat Completions on the way
out and back on the way in, so nothing else in the app changes.
"""

import json
from typing import Any, cast

import openai

from app.ai.llm.base import LLMError, Step, ToolCall


class OpenAICompatibleClient:
    def __init__(
        self,
        model: str,
        api_key: str | None,
        base_url: str | None,
        max_tokens: int = 8192,
        timeout: float = 120.0,
    ):
        if not api_key:
            raise LLMError("No LLM credentials are set. Set LLM_API_KEY and restart the server.")
        if not base_url:
            raise LLMError("No LLM endpoint is set. Set LLM_BASE_URL and restart the server.")
        try:
            self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        except openai.OpenAIError as e:
            raise LLMError(f"Could not set up the LLM client: {e}") from None
        self.model = model
        self.max_tokens = max_tokens

    def step(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Step:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=cast(Any, to_chat_messages(system, messages)),
                tools=cast(Any, to_chat_tools(tools)),
            )
        except openai.AuthenticationError:
            raise LLMError("The LLM service rejected the credentials. Check LLM_API_KEY.") from None
        except openai.RateLimitError:
            raise LLMError(
                "The LLM service is rate limiting requests. Try again in a minute."
            ) from None
        except openai.APIStatusError as e:
            raise LLMError(f"The LLM service returned an error ({e.status_code}).") from None
        except openai.APIConnectionError:
            raise LLMError(
                "Could not connect to the LLM service. Check the network and LLM_BASE_URL."
            ) from None
        except openai.OpenAIError as e:
            raise LLMError(f"Could not call the LLM service: {e}") from None

        if not response.choices:
            raise LLMError("The LLM service returned no answer.")
        choice = response.choices[0]
        message = choice.message
        text = message.content or ""
        calls = []
        for call in message.tool_calls or []:
            function = getattr(call, "function", None)
            if function is None:
                continue
            try:
                arguments = json.loads(function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(ToolCall(call.id, function.name, arguments))

        # Back in the Messages API shape, so the assistant can send it on unchanged.
        content: list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        for call in calls:
            content.append(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
            )
        return Step(
            text=text,
            tool_calls=calls,
            content=content,
            refused=choice.finish_reason == "content_filter",
        )


def to_chat_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages API tools ({name, description, input_schema}) as Chat Completions functions."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in tools
    ]


def to_chat_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages API messages as Chat Completions messages.

    text blocks become message text, tool_use blocks become the assistant's
    tool_calls, and each tool_result block becomes its own "tool" message.
    """
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        role = message["role"]
        content = message["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        texts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in content:
            kind = _get(block, "type")
            if kind == "text":
                texts.append(_get(block, "text") or "")
            elif kind == "tool_use":
                tool_calls.append(
                    {
                        "id": _get(block, "id"),
                        "type": "function",
                        "function": {
                            "name": _get(block, "name"),
                            "arguments": json.dumps(_get(block, "input") or {}),
                        },
                    }
                )
            elif kind == "tool_result":
                result = _get(block, "content")
                if not isinstance(result, str):
                    result = json.dumps(result)
                if _get(block, "is_error"):
                    result = f"Error: {result}"
                out.append(
                    {"role": "tool", "tool_call_id": _get(block, "tool_use_id"), "content": result}
                )
        if role == "assistant":
            entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(texts) or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
        elif texts:
            out.append({"role": role, "content": "\n".join(texts)})
    return out


def _get(block: Any, key: str) -> Any:
    """A field of a content block, whether it is a dict or an SDK object."""
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)
