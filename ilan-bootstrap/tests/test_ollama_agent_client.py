
import json

import pytest

import model.ollama_agent_client as client_module
from model.ollama_agent_client import (
    OllamaAgentClient,
    OllamaError,
)


class FakeHTTPResponse:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.data


def make_client(**kwargs):
    return OllamaAgentClient(
        model="gpt-oss-20b-local:latest",
        base_url="http://localhost:11434",
        timeout=10,
        **kwargs,
    )


def test_relay_credentials_are_sent_as_auth_headers(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.header_items())
        return FakeHTTPResponse({
            "model": "gpt-oss-20b-local:latest",
            "message": {"role": "assistant", "content": "ok"},
            "done": True,
        })

    monkeypatch.setattr(client_module, "urlopen", fake_urlopen)
    client = make_client(
        relay_session_id="session-123",
        relay_owner_token="secret-token",
    )
    client.chat([{"role": "user", "content": "Hello"}])

    assert captured["headers"]["X-relay-session-id"] == "session-123"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"


def test_partial_relay_credentials_are_rejected():
    with pytest.raises(ValueError, match="configured together"):
        make_client(relay_session_id="session-123")


def test_tool_result_gets_name_from_previous_tool_call():
    client = make_client()

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-123",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path": "README.md"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-123",
            "content": '{"success": true}',
        },
    ]

    prepared = client._prepare_messages(messages)

    assert prepared[1]["tool_name"] == "read_file"
    assert prepared[1]["tool_call_id"] == "call-123"
    assert prepared[1]["content"] == '{"success": true}'


def test_multiple_tool_results_keep_their_own_names():
    client = make_client()

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "list_files",
                        "arguments": {},
                    },
                },
                {
                    "id": "call-2",
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": "README.md"},
                    },
                },
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": "file list",
        },
        {
            "role": "tool",
            "tool_call_id": "call-2",
            "content": "file content",
        },
    ]

    prepared = client._prepare_messages(messages)

    assert prepared[1]["tool_name"] == "list_files"
    assert prepared[2]["tool_name"] == "read_file"


def test_tool_result_without_matching_call_is_rejected():
    client = make_client()

    messages = [
        {
            "role": "tool",
            "tool_call_id": "missing-call",
            "content": "result",
        }
    ]

    with pytest.raises(OllamaError, match="tool_name"):
        client._prepare_messages(messages)


def test_empty_assistant_content_is_preserved_as_string():
    client = make_client()

    prepared = client._prepare_messages([
        {
            "role": "assistant",
            "content": None,
        }
    ])

    assert prepared[0]["content"] == ""


def test_non_object_tool_arguments_are_rejected():
    client = make_client()

    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {
                        "name": "read_file",
                        "arguments": '["not", "an", "object"]',
                    },
                }
            ],
        }
    ]

    with pytest.raises(OllamaError, match="JSON object"):
        client._prepare_messages(messages)


def test_tool_call_response_is_normalized():
    client = make_client()

    normalized = client._normalize_tool_calls([
        {
            "function": {
                "name": "read_file",
                "arguments": {
                    "path": "README.md",
                },
            }
        }
    ])

    assert len(normalized) == 1
    assert normalized[0]["type"] == "function"
    assert normalized[0]["function"]["name"] == "read_file"
    assert normalized[0]["function"]["arguments"] == (
        '{"path": "README.md"}'
    )
    assert normalized[0]["id"] == "ollama_call_0"


def test_auto_thinking_omits_think_parameter_and_preserves_done_reason(
    monkeypatch,
):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout

        return FakeHTTPResponse({
            "model": "gpt-oss-20b-local:latest",
            "message": {
                "role": "assistant",
                "content": "",
            },
            "done": True,
            "done_reason": "length",
        })

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = make_client(thinking_mode="auto")

    result = client.chat([
        {
            "role": "user",
            "content": "Hello",
        }
    ])

    payload = json.loads(captured["request"].data.decode("utf-8"))

    assert "think" not in payload
    assert captured["timeout"] == 10
    assert result["choices"][0]["message"]["content"] == ""
    assert result["choices"][0]["finish_reason"] == "length"


def test_explicit_thinking_off_is_sent_to_ollama(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(
            request.data.decode("utf-8")
        )

        return FakeHTTPResponse({
            "model": "gpt-oss-20b-local:latest",
            "message": {
                "role": "assistant",
                "content": "Done",
            },
            "done": True,
            "done_reason": "stop",
        })

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = make_client(thinking_mode="off")

    client.chat([
        {
            "role": "user",
            "content": "Hello",
        }
    ])

    assert captured["payload"]["think"] is False


def test_tool_call_response_uses_tool_calls_finish_reason(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeHTTPResponse({
            "model": "gpt-oss-20b-local:latest",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "list_files",
                            "arguments": {},
                        }
                    }
                ],
            },
            "done": True,
            "done_reason": "stop",
        })

    monkeypatch.setattr(
        client_module,
        "urlopen",
        fake_urlopen,
    )

    client = make_client()

    result = client.chat([
        {
            "role": "user",
            "content": "List files",
        }
    ])

    choice = result["choices"][0]

    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["tool_calls"][0]["function"]["name"] == (
        "list_files"
    )
