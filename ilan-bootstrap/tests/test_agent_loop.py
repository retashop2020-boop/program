import pytest

from agent.loop import AgentLoop
from model.openrouter import OpenRouterError


class FakeRegistry:
    def definitions(self):
        return [{"type": "function", "function": {"name": "fake_tool"}}]


class FakeDispatcher:
    def __init__(self):
        self.calls = []

    def execute(self, name, arguments):
        self.calls.append((name, arguments))
        return {"value": "tool_result"}


class FakeModel:
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})

        if self.error:
            raise self.error

        if not self.responses:
            raise AssertionError("Unexpected model call")

        return self.responses.pop(0)


def make_response(message):
    return {"choices": [{"message": message}]}


def test_normal_response_uses_one_model_call():
    model = FakeModel([
        make_response({"role": "assistant", "content": "Hello"})
    ])
    dispatcher = FakeDispatcher()

    agent = AgentLoop(model, FakeRegistry(), dispatcher)

    result = agent.run("Say hello")

    assert result == "Hello"
    assert len(model.calls) == 1
    assert dispatcher.calls == []


def test_tool_call_then_final_response_uses_two_model_calls():
    model = FakeModel([
        make_response({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-1",
                "function": {
                    "name": "fake_tool",
                    "arguments": "{}",
                },
            }],
        }),
        make_response({
            "role": "assistant",
            "content": "Tool completed",
        }),
    ])
    dispatcher = FakeDispatcher()

    agent = AgentLoop(model, FakeRegistry(), dispatcher)

    result = agent.run("Use the tool")

    assert result == "Tool completed"
    assert len(model.calls) == 2
    assert len(dispatcher.calls) == 1
    assert dispatcher.calls[0][0] == "fake_tool"


def test_api_error_is_not_retried():
    rate_limit_error = OpenRouterError("OpenRouter HTTP error 429: Rate limit exceeded")
    model = FakeModel(error=rate_limit_error)
    dispatcher = FakeDispatcher()

    agent = AgentLoop(model, FakeRegistry(), dispatcher)

    with pytest.raises(OpenRouterError, match="429"):
        agent.run("Test rate limit")

    assert len(model.calls) == 1
    assert dispatcher.calls == []


def test_tool_round_limit_caps_model_calls():
    repeated_tool_call = make_response({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call-repeated",
            "function": {
                "name": "fake_tool",
                "arguments": "{}",
            },
        }],
    })

    model = FakeModel([
        repeated_tool_call,
        repeated_tool_call,
        repeated_tool_call,
    ])
    dispatcher = FakeDispatcher()

    agent = AgentLoop(model, FakeRegistry(), dispatcher)

    result = agent.run("Keep requesting the tool")

    assert "tool-call limit" in result
    assert len(model.calls) == 3
    assert len(dispatcher.calls) == 2
