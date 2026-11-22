import io
import json
from urllib.error import HTTPError, URLError

import pytest

from model.gemini import GeminiClient, GeminiError


class FakeResponse:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self):
        if isinstance(self.data, bytes):
            return self.data
        return json.dumps(self.data).encode("utf-8")


def make_client(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    return GeminiClient()


def test_client_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
        GeminiClient()


def test_client_uses_environment_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "test-model")

    client = GeminiClient()

    assert client.model == "test-model"


def test_convert_messages_separates_system_instruction():
    client = GeminiClient.__new__(GeminiClient)

    system, contents = client._convert_messages([
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "سلام"},
    ])

    assert system == [{"text": "System prompt"}]
    assert contents == [{
        "role": "user",
        "parts": [{"text": "سلام"}],
    }]


def test_convert_tools_to_gemini_function_declarations():
    client = GeminiClient.__new__(GeminiClient)

    tools = client._convert_tools([{
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a workspace file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        },
    }])

    assert tools[0]["functionDeclarations"][0]["name"] == "read_file"
    assert tools[0]["functionDeclarations"][0]["parameters"]["required"] == ["path"]


def test_convert_assistant_tool_call_and_tool_response():
    client = GeminiClient.__new__(GeminiClient)

    system, contents = client._convert_messages([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-1",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "README.md"}',
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": '{"success": true, "result": "file content"}',
        },
    ])

    assert system == []
    assert contents[0]["role"] == "model"
    assert contents[0]["parts"][0]["functionCall"] == {
        "name": "read_file",
        "args": {"path": "README.md"},
    }
    assert contents[1]["role"] == "user"
    assert contents[1]["parts"][0]["functionResponse"] == {
        "name": "read_file",
        "response": {"success": True, "result": "file content"},
    }


def test_invalid_tool_arguments_raise_gemini_error():
    client = GeminiClient.__new__(GeminiClient)

    with pytest.raises(GeminiError, match="Invalid JSON"):
        client._convert_messages([{
            "role": "assistant",
            "tool_calls": [{
                "id": "call-1",
                "function": {
                    "name": "read_file",
                    "arguments": "{invalid",
                },
            }],
        }])


def test_unknown_tool_call_id_raises_gemini_error():
    client = GeminiClient.__new__(GeminiClient)

    with pytest.raises(GeminiError, match="Unknown tool_call_id"):
        client._convert_messages([{
            "role": "tool",
            "tool_call_id": "missing-call",
            "content": "{}",
        }])


def test_chat_converts_text_response(monkeypatch):
    client = make_client(monkeypatch)

    response_data = {
        "candidates": [{
            "content": {
                "parts": [{"text": "سلام، اتصال برقرار است."}],
            },
            "finishReason": "STOP",
        }],
    }

    def fake_urlopen(request, timeout):
        assert request.full_url.endswith(
            "/gemini-3.5-flash-lite:generateContent"
        )
        assert request.get_header("X-goog-api-key") == "fake-key"
        assert timeout == 90
        return FakeResponse(response_data)

    monkeypatch.setattr("model.gemini.urlopen", fake_urlopen)

    result = client.chat([
        {"role": "user", "content": "سلام"},
    ])

    assert result["choices"][0]["message"] == {
        "role": "assistant",
        "content": "سلام، اتصال برقرار است.",
    }
    assert result["choices"][0]["finish_reason"] == "STOP"


def test_chat_converts_function_call_response(monkeypatch):
    client = make_client(monkeypatch)

    response_data = {
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": "read_file",
                        "args": {"path": "README.md"},
                    },
                }],
            },
            "finishReason": "STOP",
        }],
    }

    monkeypatch.setattr(
        "model.gemini.urlopen",
        lambda request, timeout: FakeResponse(response_data),
    )

    result = client.chat([
        {"role": "user", "content": "Read README"},
    ])

    message = result["choices"][0]["message"]

    assert message["role"] == "assistant"
    assert message["content"] is None
    assert message["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(
        message["tool_calls"][0]["function"]["arguments"]
    ) == {"path": "README.md"}


def test_chat_http_error(monkeypatch):
    client = make_client(monkeypatch)

    def fake_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            429,
            "Rate limit",
            {},
            io.BytesIO(b'{"error": "quota exceeded"}'),
        )

    monkeypatch.setattr("model.gemini.urlopen", fake_urlopen)

    with pytest.raises(GeminiError, match="HTTP error 429"):
        client.chat([{"role": "user", "content": "test"}])


def test_chat_connection_error(monkeypatch):
    client = make_client(monkeypatch)

    def fake_urlopen(request, timeout):
        raise URLError("connection failed")

    monkeypatch.setattr("model.gemini.urlopen", fake_urlopen)

    with pytest.raises(GeminiError, match="Could not connect"):
        client.chat([{"role": "user", "content": "test"}])


def test_chat_invalid_json(monkeypatch):
    client = make_client(monkeypatch)

    monkeypatch.setattr(
        "model.gemini.urlopen",
        lambda request, timeout: FakeResponse(b"not-json"),
    )

    with pytest.raises(GeminiError, match="invalid JSON"):
        client.chat([{"role": "user", "content": "test"}])


def test_chat_without_candidates_raises_error(monkeypatch):
    client = make_client(monkeypatch)

    monkeypatch.setattr(
        "model.gemini.urlopen",
        lambda request, timeout: FakeResponse({"candidates": []}),
    )

    with pytest.raises(GeminiError, match="no candidates"):
        client.chat([{"role": "user", "content": "test"}])


def test_convert_tools_removes_additional_properties_recursively():
    client = GeminiClient.__new__(GeminiClient)

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "config": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "enabled": {"type": "boolean"},
                },
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                    },
                },
            },
        },
        "required": ["config"],
    }

    result = client._convert_tools([{
        "type": "function",
        "function": {
            "name": "test_tool",
            "parameters": schema,
        },
    }])

    parameters = result[0]["functionDeclarations"][0]["parameters"]

    assert "additionalProperties" not in parameters
    assert "additionalProperties" not in parameters["properties"]["config"]
    assert "additionalProperties" not in (
        parameters["properties"]["items"]["items"]
    )
    assert parameters["required"] == ["config"]
    assert parameters["properties"]["config"]["properties"]["enabled"] == {
        "type": "boolean"
    }


def test_function_call_preserves_thought_signature(monkeypatch):
    client = make_client(monkeypatch)
    signature = "test-signature-123"

    response_data = {
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": "read_file",
                        "args": {"path": "README.md"},
                    },
                    "thoughtSignature": signature,
                }],
            },
            "finishReason": "STOP",
        }],
    }

    monkeypatch.setattr(
        "model.gemini.urlopen",
        lambda request, timeout: FakeResponse(response_data),
    )

    result = client.chat([
        {"role": "user", "content": "Read README"},
    ])

    assistant_message = result["choices"][0]["message"]
    tool_call = assistant_message["tool_calls"][0]

    assert tool_call["thought_signature"] == signature

    _, contents = client._convert_messages([
        assistant_message,
    ])

    function_call_part = contents[0]["parts"][0]

    assert function_call_part["functionCall"] == {
        "name": "read_file",
        "args": {"path": "README.md"},
    }
    assert function_call_part["thoughtSignature"] == signature


def test_function_call_preserves_thought_signature(monkeypatch):
    client = make_client(monkeypatch)
    signature = "test-signature-123"

    response_data = {
        "candidates": [{
            "content": {
                "parts": [{
                    "functionCall": {
                        "name": "read_file",
                        "args": {"path": "README.md"},
                    },
                    "thoughtSignature": signature,
                }],
            },
            "finishReason": "STOP",
        }],
    }

    monkeypatch.setattr(
        "model.gemini.urlopen",
        lambda request, timeout: FakeResponse(response_data),
    )

    result = client.chat([
        {"role": "user", "content": "Read README"},
    ])

    assistant_message = result["choices"][0]["message"]
    tool_call = assistant_message["tool_calls"][0]

    assert tool_call["thought_signature"] == signature

    _, contents = client._convert_messages([
        assistant_message,
    ])

    function_call_part = contents[0]["parts"][0]

    assert function_call_part["functionCall"] == {
        "name": "read_file",
        "args": {"path": "README.md"},
    }
    assert function_call_part["thoughtSignature"] == signature



