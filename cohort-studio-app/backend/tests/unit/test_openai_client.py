"""The OpenAI-compatible client translates to Chat Completions and back."""

import json
from types import SimpleNamespace

import pytest

from app.ai.llm.base import LLMError
from app.ai.llm.openai_client import OpenAICompatibleClient, to_chat_messages, to_chat_tools

TOOLS = [{"name": "ask_user", "description": "Ask", "input_schema": {"type": "object"}}]


def response(text, calls=(), finish="stop"):
    tool_calls = [
        SimpleNamespace(
            id=i, type="function", function=SimpleNamespace(name=n, arguments=json.dumps(a))
        )
        for i, n, a in calls
    ]
    message = SimpleNamespace(content=text, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)])


def make(reply):
    client = OpenAICompatibleClient("m", "key", "https://llm.example/v1")
    sent = {}

    def create(**kwargs):
        sent.update(kwargs)
        return reply

    client._client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    return client, sent


def test_tools_become_functions():
    out = to_chat_tools(TOOLS)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "ask_user",
                "description": "Ask",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_tool_calls_come_back_in_messages_api_shape():
    client, sent = make(response("Let me ask.", [("c1", "ask_user", {"question": "Age?"})]))
    step = client.step("sys", [{"role": "user", "content": "women over 60"}], TOOLS)
    assert step.text == "Let me ask."
    assert step.tool_calls[0].name == "ask_user"
    assert step.tool_calls[0].input == {"question": "Age?"}
    assert step.content[1] == {
        "type": "tool_use",
        "id": "c1",
        "name": "ask_user",
        "input": {"question": "Age?"},
    }
    assert sent["messages"][0] == {"role": "system", "content": "sys"}
    assert sent["max_tokens"] == 8192


def test_a_full_turn_is_translated():
    history = [
        {"role": "user", "content": "women over 60"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Checking."},
                {"type": "tool_use", "id": "c1", "name": "list_values", "input": {"a": 1}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": '["F","M"]'},
                {"type": "tool_result", "tool_use_id": "c2", "content": "bad", "is_error": True},
            ],
        },
    ]
    out = to_chat_messages("sys", history)
    assert out[1] == {"role": "user", "content": "women over 60"}
    assert out[2]["role"] == "assistant"
    assert out[2]["content"] == "Checking."
    assert out[2]["tool_calls"][0]["function"] == {"name": "list_values", "arguments": '{"a": 1}'}
    assert out[3] == {"role": "tool", "tool_call_id": "c1", "content": '["F","M"]'}
    assert out[4] == {"role": "tool", "tool_call_id": "c2", "content": "Error: bad"}


def test_missing_settings_are_reported():
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        OpenAICompatibleClient("m", None, "https://llm.example/v1")
    with pytest.raises(LLMError, match="LLM_BASE_URL"):
        OpenAICompatibleClient("m", "key", None)
